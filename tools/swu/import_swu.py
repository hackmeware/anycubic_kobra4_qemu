#!/usr/bin/env python3
"""Offline-first SWU staging; no firmware, passwords or update-code execution."""
import argparse, datetime, getpass, gzip, hashlib, http.client, importlib.util, ipaddress
import json, os, socket, ssl, stat, struct, subprocess, sys, tarfile, time, urllib.parse, zipfile
from pathlib import Path, PurePosixPath
KNOWN_SHA256 = 'ba1938de6241e6918f4ab19450e2a5aa876ceb71a35fc038080026839a975c19'
KNOWN_VERSION = 'K4_1.2.1.3'
MAX_SWU = 512 * 1024 * 1024
MAX_MEMBER = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
MAX_FILES = 20000
CHUNK = 1024 * 1024
class SafeError(Exception):
    pass

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(CHUNK), b''): h.update(b)
    return h.hexdigest()

def safe_name(name):
    if not name or '\\' in name or ':' in name or any(ord(c)<32 or ord(c)==127 for c in name):
        raise SafeError('Unsafe archive path')
    while name.startswith('./'): name = name[2:]
    name = name.rstrip('/')
    if not name or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/')):
        raise SafeError('Absolute, empty or traversing archive path')
    if len(name)>512 or len(name.split('/'))>32: raise SafeError('Archive path limit')
    return PurePosixPath(name)

def safe_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.fragment:
        raise SafeError('Use HTTPS without credentials or fragments')
    try: port = p.port or 443
    except ValueError: raise SafeError('Invalid URL port')
    if port!=443 or any(ord(c)<32 or ord(c)==127 for c in url): raise SafeError('Unsafe URL')
    return p

def public_addresses(host):
    result = []
    for fam, typ, proto, _, addr in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(addr[0]).is_global: raise SafeError('Non-public download address refused')
        if (fam,typ,proto,addr) not in result: result.append((fam,typ,proto,addr))
    if not result: raise SafeError('No public download address')
    return result

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,addresses):
        super().__init__(host,timeout=30,context=ssl.create_default_context())
        self.addresses=addresses
    def connect(self):
        last=None
        for fam,typ,proto,addr in self.addresses:
            sock=socket.socket(fam,typ,proto);sock.settimeout(self.timeout)
            try:
                sock.connect(addr)
                self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
                return
            except (OSError,ssl.SSLError) as e: last=e;sock.close()
        raise SafeError('HTTPS connection failed') from last

def _download_worker(url,target):
    initial=safe_url(url);current=url;deadline=time.monotonic()+180
    for redirects in range(4):
        p=safe_url(current)
        if time.monotonic()>deadline: raise SafeError('Download total time limit')
        if p.hostname.lower()!=initial.hostname.lower(): raise SafeError('Cross-host redirect refused; supply verified final URL explicitly')
        con=PinnedHTTPS(p.hostname,public_addresses(p.hostname))
        try:
            path=urllib.parse.urlunsplit(('','',p.path or '/',p.query,''))
            con.request('GET',path,headers={'User-Agent':'Kobra-SWU-import/1','Accept-Encoding':'identity'})
            r=con.getresponse()
            if r.status in (301,302,303,307,308):
                if redirects==3 or not r.getheader('Location'): raise SafeError('Redirect limit')
                current=urllib.parse.urljoin(current,r.getheader('Location'));continue
            if r.status!=200: raise SafeError('Download HTTP status '+str(r.status))
            if r.getheader('Content-Encoding','identity').lower() not in ('','identity'): raise SafeError('Unexpected HTTP content encoding')
            declared=r.getheader('Content-Length')
            if declared and (not declared.isdigit() or int(declared)>MAX_SWU): raise SafeError('Invalid or oversized download')
            count=0
            with target.open('xb') as f:
                while True:
                    if time.monotonic()>deadline: raise SafeError('Download total time limit')
                    b=r.read1(CHUNK)
                    if not b: break
                    count+=len(b)
                    if count>MAX_SWU: raise SafeError('Download size limit')
                    f.write(b)
            target.chmod(0o600)
            if declared and count!=int(declared): raise SafeError('Incomplete download')
            return {'kind':'https','url_without_query':urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,'','')),
                    'query_omitted':bool(p.query),'url_sha256':hashlib.sha256(current.encode()).hexdigest(),'bytes':count}
        finally: con.close()
    raise SafeError('Redirect failure')

def download(url,target):
    # A separate instance of THIS trusted script bounds DNS, TLS, headers and
    # slow-drip body time together. URL query data travels over stdin, not argv.
    request=json.dumps({'url':url,'target':str(target)})
    try:
        result=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--download-worker'],
                              input=request,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              timeout=180,check=False)
    except subprocess.TimeoutExpired as e:
        raise SafeError('Download hard time limit exceeded; partial file retained privately') from e
    if result.returncode!=0: raise SafeError('HTTPS download failed or unsupported redirect; no preparation performed')
    try: report=json.loads(result.stdout)
    except (ValueError,TypeError) as e: raise SafeError('Invalid download worker result') from e
    if not isinstance(report,dict) or report.get('kind')!='https': raise SafeError('Invalid download result')
    return report

class TarGuard:
    """Inspect every raw512-byte header BEFORE tarfile can process PAX metadata."""
    def __init__(self,source,limit):
        self.source=source;self.limit=limit;self.total=0;self.buffer=b''
        self.pending=0;self.headers=0;self.metadata=0;self.ended=False
    def read(self,n):
        if n<0 or n>CHUNK: raise SafeError('Unbounded TAR read refused')
        data=self.source.read(n);self.total+=len(data)
        if self.total>self.limit: raise SafeError('Decompressed TAR byte limit')
        self.buffer+=data
        while len(self.buffer)>=512:
            block,self.buffer=self.buffer[:512],self.buffer[512:]
            if self.pending: self.pending-=1;continue
            if block==bytes(512): self.ended=True;continue
            if self.ended: raise SafeError('Nonzero trailing/concatenated TAR data')
            member=tarfile.TarInfo.frombuf(block,'utf-8','strict')
            self.headers+=1
            if self.headers>MAX_FILES: raise SafeError('TAR header count limit')
            if member.size<0 or member.size>MAX_MEMBER: raise SafeError('TAR header size limit')
            if member.type in (tarfile.XHDTYPE,tarfile.XGLTYPE,tarfile.GNUTYPE_LONGNAME,tarfile.GNUTYPE_LONGLINK):
                self.metadata+=member.size
                if member.size>65536 or self.metadata>16*1024*1024: raise SafeError('TAR extended metadata limit')
            elif not (member.isreg() or member.isdir()):
                raise SafeError('TAR header link/special/sparse file refused')
            self.pending=(member.size+511)//512
        if not data and (self.pending or self.buffer): raise SafeError('Truncated TAR stream')
        return data

def fresh_directory(path):
    p=Path(path).absolute()
    if p.exists() or p.is_symlink(): raise SafeError('Output must be a NEW directory')
    if not p.parent.is_dir(): raise SafeError('Output parent must exist')
    p.mkdir(mode=0o700)
    return p.resolve()

class Budget:
    def __init__(self): self.files=0;self.bytes=0
    def add(self,size):
        self.files+=1;self.bytes+=size
        if size<0 or size>MAX_MEMBER or self.files>MAX_FILES or self.bytes>MAX_EXPANDED:
            raise SafeError('Archive expansion budget exceeded')

def bounded_copy(src,target,size):
    if size<0 or size>MAX_MEMBER: raise SafeError('Member size limit')
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);count=0
    with target.open('xb') as out:
        while True:
            b=src.read(min(CHUNK,size-count+1))
            if not b: break
            count+=len(b)
            if count>size: raise SafeError('Member larger than declared')
            out.write(b)
    target.chmod(0o600)
    if count!=size: raise SafeError('Truncated member')

def inspect_zip(path):
    # Bound central-directory allocation before ZipFile parses untrusted metadata.
    size=Path(path).stat().st_size
    with open(path,'rb') as raw:
        raw.seek(max(0,size-65557));tail=raw.read(65557)
    offset=tail.rfind(b'PK\x05\x06')
    if offset<0 or len(tail)-offset<22: raise SafeError('Missing ZIP end record')
    eocd_absolute=max(0,size-65557)+offset
    if eocd_absolute>=20:
        with open(path,'rb') as raw:
            raw.seek(eocd_absolute-20)
            if raw.read(4)==b'PK\x06\x07': raise SafeError('ZIP64 locator not supported')

    _,disk,cd_disk,on_disk,total,cd_size,cd_offset,comment=struct.unpack('<4s4H2IH',tail[offset:offset+22])
    if len(tail)-offset!=22+comment or disk or cd_disk or on_disk!=total:
        raise SafeError('Invalid/multipart ZIP end record')
    if total>MAX_FILES or cd_size>16*1024*1024 or cd_offset+cd_size>size:
        raise SafeError('ZIP metadata size/count limit; ZIP64 not supported')
    with zipfile.ZipFile(path) as z:
        if len(z.infolist())>MAX_FILES: raise SafeError('ZIP entry count limit')
        seen=set();result=[]
        for i in z.infolist():
            name=str(safe_name(i.filename))
            if name in seen: raise SafeError('Duplicate normalized ZIP path')
            seen.add(name);ftype=stat.S_IFMT(i.external_attr>>16)
            if ftype not in (0,stat.S_IFREG,stat.S_IFDIR): raise SafeError('ZIP link/special file refused')
            if i.file_size>MAX_MEMBER or i.compress_size>MAX_SWU: raise SafeError('ZIP size limit')
            result.append({'path':name,'bytes':i.file_size,'encrypted':bool(i.flag_bits&1),'method':i.compress_type,'directory':i.is_dir()})
        return result

def extract_outer(path,dest,password,budget):
    info=inspect_zip(path);files={r['path'] for r in info if not r['directory']}
    if not {'update_swu/setup.tar.gz','update_swu/setup.sig'}<=files: raise SafeError('Unsupported SWU layout')
    if files-{'update_swu/setup.tar.gz','update_swu/setup.sig','update_swu/.gitkeep'}: raise SafeError('Unexpected SWU member')
    if any(r['encrypted'] for r in info) and password is None: raise SafeError('Encrypted SWU requires --password-prompt; no password is bundled')
    with zipfile.ZipFile(path) as z:
        for i in z.infolist():
            if i.is_dir(): continue
            budget.add(i.file_size)
            with z.open(i,pwd=password) as src: bounded_copy(src,dest/safe_name(i.filename),i.file_size)
    return info

def extract_tar(path,dest,budget):
    seen=set();files=[]
    with open(path,'rb') as probe: magic=probe.read(2)
    opener=gzip.open if magic==b'\x1f\x8b' else open
    with opener(path,'rb') as raw:
        guard=TarGuard(raw,MAX_EXPANDED-budget.bytes)
        with tarfile.open(fileobj=guard,mode='r|') as t:
            for m in t:
                if m.name in ('.','./') and m.isdir(): continue
                name=str(safe_name(m.name))
                if name in seen: raise SafeError('Duplicate normalized TAR path')
                seen.add(name)
                if len(seen)>MAX_FILES: raise SafeError('TAR entry count limit')
                if m.isdir(): continue
                if not m.isreg() or m.issparse(): raise SafeError('TAR links/special/sparse files refused')
                budget.add(m.size)
                with t.extractfile(m) as src: bounded_copy(src,dest/name,m.size)
                files.append({'path':name,'bytes':m.size,'sha256':digest(dest/name)})
        # Finish decompression to enforce gzip CRC/EOF and trailing metadata bounds.
        while guard.read(CHUNK): pass
    return files

def verify_signature(setup,signature,key,key_hash):
    key=Path(key).resolve(strict=True)
    if not key.is_file() or key.stat().st_size>1024*1024 or digest(key)!=key_hash.lower():
        raise SafeError('Public-key SHA256/size mismatch')
    result=subprocess.run(['openssl','dgst','-sha256','-verify',str(key),'-signature',str(signature),str(setup)],
                          stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,check=False)
    if result.returncode!=0: raise SafeError('SHA256 signature verification failed')
    return {'algorithm':'openssl dgst -sha256','public_key_sha256':key_hash.lower(),
            'verified_relative_to_user_supplied_key':True,'manufacturer_key_authenticity_not_established_by_tool':True}

def prepare_selected_inputs(output,setup_files,budget):
    here=Path(__file__).resolve().parent
    profile=json.loads((here/'firmware-profile.json').read_text())
    parser=here/'rv1106_fit.py'
    if digest(parser)!=profile['fit_parser_sha256']: raise SafeError('FIT parser source hash changed')
    locations=[(output/'setup'/r['path'],r) for r in setup_files]
    ota=[p for p,r in locations if p.name=='update_ota.tar']
    if len(ota)>1: raise SafeError('Ambiguous nested update_ota.tar')
    if ota:
        rows=extract_tar(ota[0],output/'ota',budget)
        locations.extend((output/'ota'/r['path'],r) for r in rows)
    inputs=output/'inputs';inputs.mkdir(mode=0o700)
    installed=[]
    for name,expected in profile['expected_inputs'].items():
        if name in ('offline-emmc.img','disk-layout.json'): continue
        matches=[p for p,r in locations if r['sha256']==expected['sha256'] and r['bytes']==expected['bytes']]
        if matches:
            with matches[0].open('rb') as src: bounded_copy(src,inputs/name,expected['bytes'])
            installed.append(name)
    boots=[p for p,r in locations if r['sha256']==profile['boot_img_sha256']]
    if boots:
        spec=importlib.util.spec_from_file_location('kobra_trusted_fit_parser',parser)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        data=boots[0].read_bytes()
        if len(data)>module.MAX_INPUT: raise SafeError('FIT input size limit')
        nodes,total=module.fdt(data)
        for path in nodes:
            if path.startswith('/images/') and path.count('/')==2:
                info,payload=module.fit_image(data,nodes,total,path.rsplit('/',1)[1])
                for name in ('kernel-zImage','kernel-board-dtb.dtb'):
                    expected=profile['expected_inputs'][name]
                    if name not in installed and len(payload)==expected['bytes'] and hashlib.sha256(payload).hexdigest()==expected['sha256']:
                        with (inputs/name).open('xb') as out: out.write(payload)
                        (inputs/name).chmod(0o600);installed.append(name)
    return {'verified_input_files':installed,
            'missing_required_inputs':[n for n in profile['expected_inputs'] if n not in installed],
            'profile_sha256':digest(here/'firmware-profile.json'),
            'notes':'Only byte-matching original input files copied. No dummy files, synthetic filesystem recreation or pin relaxation.'}

def run(args):
    output=fresh_directory(args.output)
    report={'schema':1,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'INCOMPLETE',
            'firmware_executed':False,'manufacturer_authenticity_verified':False,'emulator_inputs_prepared':False,
            'license':'User-supplied firmware; no redistribution permission asserted'}
    try:
        if args.url:
            if not args.sha256: raise SafeError('--url requires independently obtained --sha256')
            source=output/'download.swu';report['source']=download(args.url,source)
        else:
            source=Path(args.swu).resolve(strict=True)
            if not source.is_file() or source.stat().st_size>MAX_SWU: raise SafeError('Input must be a regular bounded SWU')
            report['source']={'kind':'local','filename':source.name,'bytes':source.stat().st_size}
            with source.open('rb') as src: bounded_copy(src,output/'input.swu',source.stat().st_size)
            source=output/'input.swu'
        sha=digest(source);report['swu_sha256']=sha
        if args.sha256 and sha!=args.sha256.lower(): raise SafeError('SWU SHA256 mismatch; no extraction performed')
        report['outer_inventory']=inspect_zip(source)
        if args.inspect: report['status']='INVENTORIED_ONLY';return report
        if sha!=KNOWN_SHA256: raise SafeError('Unsupported firmware hash/version; use --inspect then review new profile')
        report['version']=KNOWN_VERSION
        if args.password_prompt and not sys.stdin.isatty(): raise SafeError('Password prompt requires an interactive terminal')
        password=getpass.getpass('SWU password (not saved): ').encode() if args.password_prompt else None
        budget=Budget();extract_outer(source,output/'outer',password,budget);password=None
        setup=output/'outer/update_swu/setup.tar.gz';sig=output/'outer/update_swu/setup.sig'
        if args.verify_sha256_public_key:
            report['signature']=verify_signature(setup,sig,args.verify_sha256_public_key,args.public_key_sha256)
        report['setup_files']=extract_tar(setup,output/'setup',budget)
        report['setup_sha256']=digest(setup);report['signature_sha256']=digest(sig)
        report['r9_inputs']=prepare_selected_inputs(output,report['setup_files'],budget)
        report['status']='STAGED_NOT_PREPARED'
        report['remaining']=['Nested OTA/FIT/MCU mapping and generated app.ext4/userdata.ext4/data.ext4 must match current R9 pins',
                             'A staged SWU is not an emulator-ready image; no update.sh or other contained code was executed']
        return report
    except Exception as e:
        report['error_type']=type(e).__name__
        if isinstance(e,SafeError): report['error']=str(e)
        raise
    finally:
        (output/'IMPORT-REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
        (output/'IMPORT-REPORT.json').chmod(0o600)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    src=p.add_mutually_exclusive_group(required=True)
    src.add_argument('--swu');src.add_argument('--url')
    p.add_argument('--sha256');p.add_argument('--output',required=True)
    p.add_argument('--inspect',action='store_true')
    p.add_argument('--password-prompt',action='store_true')
    p.add_argument('--verify-sha256-public-key',help='Optional user-trusted public key; explicitly selects SHA256 verification')
    p.add_argument('--public-key-sha256')
    a=p.parse_args()
    for value in (a.sha256,a.public_key_sha256):
        if value and (len(value)!=64 or any(c not in '0123456789abcdefABCDEF' for c in value)): p.error('SHA256 must contain64 hexadecimal characters')
    if bool(a.verify_sha256_public_key)!=bool(a.public_key_sha256): p.error('Public key and its SHA256 must be supplied together')
    try:
        r=run(a);print(r['status'])
        if r['status']=='STAGED_NOT_PREPARED':
            print('Extracted files are NOT emulator-ready. Read IMPORT-REPORT.json.');return 3
        return 0
    except (SafeError,OSError,ValueError,RuntimeError,NotImplementedError,zipfile.BadZipFile,tarfile.TarError,subprocess.TimeoutExpired,http.client.HTTPException) as e:
        print('Import stopped: '+(str(e) if isinstance(e,SafeError) else type(e).__name__))
        return 2
if __name__=='__main__':
    if sys.argv[1:]==['--download-worker']:
        try:
            request=json.loads(sys.stdin.read(16384))
            result=_download_worker(request['url'],Path(request['target']))
            print(json.dumps(result))
        except Exception:
            raise SystemExit(2)
    else:
        raise SystemExit(main())
