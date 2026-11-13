import argparse, hashlib, io, json, os, stat, tarfile, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch, Mock
import import_swu as imp

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def tar(self,rows):
        p=self.root/'fixture.tar.gz'
        with tarfile.open(p,'w:gz') as t:
            for name,kind,data in rows:
                m=tarfile.TarInfo(name);m.type=kind
                if kind==tarfile.REGTYPE:m.size=len(data);t.addfile(m,io.BytesIO(data))
                else:m.linkname='outside';t.addfile(m)
        return p
    def zip(self,entries):
        p=self.root/'fixture.swu'
        with zipfile.ZipFile(p,'w') as z:
            for name,data in entries:z.writestr(name,data)
        return p
    def args(self,p,**kw):
        a=dict(swu=str(p),url=None,sha256=None,output=str(self.root/'out'),inspect=True,
               password_prompt=False,verify_sha256_public_key=None,public_key_sha256=None)
        a.update(kw);return argparse.Namespace(**a)
    def test_safe_name(self):
        self.assertEqual(str(imp.safe_name('./update_swu/setup.tar.gz')),'update_swu/setup.tar.gz')
    def test_bad_names(self):
        for name in ('../x','/x','a/../x','C:/x','a\\b','a//b','a\0b',''):
            with self.subTest(name=name),self.assertRaises(imp.SafeError):imp.safe_name(name)
    def test_existing_destination_refused(self):
        with self.assertRaises(imp.SafeError):imp.fresh_directory(self.root)
    def test_outer_inventory_and_private_copy(self):
        p=self.zip([('update_swu/setup.tar.gz',b'x'),('update_swu/setup.sig',b'y')])
        sha=imp.digest(p);r=imp.run(self.args(p))
        self.assertEqual(r['status'],'INVENTORIED_ONLY')
        self.assertEqual(imp.digest(self.root/'out/input.swu'),sha);self.assertEqual(imp.digest(p),sha)
        self.assertEqual((self.root/'out').stat().st_mode&0o777,0o700)
    def test_hash_mismatch_blocks_extraction(self):
        p=self.zip([('x',b'x')])
        with self.assertRaises(imp.SafeError):imp.run(self.args(p,sha256='0'*64))
        self.assertFalse((self.root/'out/outer').exists())
    def test_unknown_version_not_staged(self):
        p=self.zip([('update_swu/setup.tar.gz',b'x'),('update_swu/setup.sig',b'y')])
        with self.assertRaises(imp.SafeError):imp.run(self.args(p,inspect=False))
    def test_zip_traversal(self):
        p=self.zip([('../escape',b'x')])
        with self.assertRaises(imp.SafeError):imp.inspect_zip(p)
    def test_zip_duplicate_normalized(self):
        p=self.zip([('a',b'x'),('./a',b'y')])
        with self.assertRaises(imp.SafeError):imp.inspect_zip(p)
    def test_zip_symlink(self):
        p=self.root/'link.zip'
        with zipfile.ZipFile(p,'w') as z:
            i=zipfile.ZipInfo('link');i.create_system=3;i.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(i,'../outside')
        with self.assertRaises(imp.SafeError):imp.inspect_zip(p)
    def test_unexpected_outer_member(self):
        p=self.zip([('update_swu/setup.tar.gz',b'x'),('update_swu/setup.sig',b'y'),('run.sh',b'bad')])
        with self.assertRaises(imp.SafeError):imp.extract_outer(p,self.root/'outer',None,imp.Budget())
    def test_tar_regular(self):
        p=self.tar([('./data/a',tarfile.REGTYPE,b'hello')]);rows=imp.extract_tar(p,self.root/'stage',imp.Budget())
        self.assertEqual(rows[0]['sha256'],hashlib.sha256(b'hello').hexdigest())
        self.assertEqual((self.root/'stage/data/a').stat().st_mode&0o777,0o600)
    def test_tar_links_special(self):
        for kind in (tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.CHRTYPE,tarfile.FIFOTYPE):
            p=self.tar([('link',kind,b'')])
            with self.subTest(kind=kind),self.assertRaises(imp.SafeError):imp.extract_tar(p,self.root/'stage',imp.Budget())
    def test_tar_traversal(self):
        p=self.tar([('../escape',tarfile.REGTYPE,b'x')])
        with self.assertRaises(imp.SafeError):imp.extract_tar(p,self.root/'stage',imp.Budget())
    def test_budget(self):
        with patch.object(imp,'MAX_EXPANDED',4),self.assertRaises(imp.SafeError):imp.Budget().add(5)
    def test_truncated_member(self):
        with self.assertRaises(imp.SafeError):imp.bounded_copy(io.BytesIO(b'x'),self.root/'x',2)
    def test_oversized_member(self):
        with self.assertRaises(imp.SafeError):imp.bounded_copy(io.BytesIO(b'xy'),self.root/'x',1)
    def test_url_rules(self):
        for url in ('http://example.com/x','https://user:pw@example.com/x','https://example.com:8443/x','https://example.com/x#f'):
            with self.subTest(url=url),self.assertRaises(imp.SafeError):imp.safe_url(url)
    def test_nonpublic_dns_blocked(self):
        with patch.object(imp.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),self.assertRaises(imp.SafeError):
            imp.public_addresses('example.com')
    def test_download_mocked_success(self):
        response=Mock();response.status=200;response.getheader.side_effect=lambda k,d=None:{'Content-Length':'3'}.get(k,d)
        response.read1.side_effect=[b'abc',b''];con=Mock();con.getresponse.return_value=response
        with patch.object(imp,'PinnedHTTPS',return_value=con),patch.object(imp,'public_addresses',return_value=[]):
            report=imp._download_worker('https://example.com/fw?token=not-a-real-token',self.root/'download')
        self.assertEqual((self.root/'download').read_bytes(),b'abc')
        self.assertNotIn('token=',json.dumps(report))
    def test_cross_host_redirect_blocked(self):
        response=Mock();response.status=302;response.getheader.return_value='https://other.example/fw';con=Mock();con.getresponse.return_value=response
        with patch.object(imp,'PinnedHTTPS',return_value=con),patch.object(imp,'public_addresses',return_value=[]),self.assertRaises(imp.SafeError):
            imp._download_worker('https://example.com/fw',self.root/'download')
    def test_synthetic_known_profile_stages_but_never_claims_ready(self):
        t=self.tar([('./readme.txt',tarfile.REGTYPE,b'fixture only')])
        p=self.zip([('update_swu/setup.tar.gz',t.read_bytes()),('update_swu/setup.sig',b'not a real signature')])
        with patch.object(imp,'KNOWN_SHA256',imp.digest(p)):
            r=imp.run(self.args(p,inspect=False))
        self.assertEqual(r['status'],'STAGED_NOT_PREPARED');self.assertFalse(r['emulator_inputs_prepared'])
        self.assertFalse(r['manufacturer_authenticity_verified'])
        self.assertIn('offline-emmc.img',r['r9_inputs']['missing_required_inputs'])
    def test_key_hash_checked_before_openssl(self):
        key=self.root/'key.pem';key.write_text('not a real key')
        with patch.object(imp.subprocess,'run') as run,self.assertRaises(imp.SafeError):
            imp.verify_signature(self.root/'x',self.root/'sig',key,'0'*64)
        run.assert_not_called()

    def test_tar_pax_metadata_limit(self):
        h=tarfile.TarInfo('pax');h.type=tarfile.XHDTYPE;h.size=65537
        with self.assertRaises(imp.SafeError):imp.TarGuard(io.BytesIO(h.tobuf()),imp.MAX_EXPANDED).read(512)
    def test_tar_root_headers_counted(self):
        h=tarfile.TarInfo('.');h.type=tarfile.DIRTYPE
        with patch.object(imp,'MAX_FILES',1),self.assertRaises(imp.SafeError):
            imp.TarGuard(io.BytesIO(h.tobuf()*2),imp.MAX_EXPANDED).read(1024)
    def test_download_wall_timeout(self):
        with patch.object(imp.subprocess,'run',side_effect=imp.subprocess.TimeoutExpired('fixture',180)),self.assertRaises(imp.SafeError):
            imp.download('https://example.com/fw',self.root/'download')

    def test_zip64_locator_refused_before_zipfile(self):
        p=self.zip([('a',b'x')]);data=p.read_bytes();eocd=data.rfind(b'PK\x05\x06')
        p.write_bytes(data[:eocd]+b'PK\x06\x07'+bytes(16)+data[eocd:])
        with patch.object(imp.zipfile,'ZipFile') as parser,self.assertRaises(imp.SafeError):
            imp.inspect_zip(p)
        parser.assert_not_called()

if __name__=='__main__':unittest.main()
