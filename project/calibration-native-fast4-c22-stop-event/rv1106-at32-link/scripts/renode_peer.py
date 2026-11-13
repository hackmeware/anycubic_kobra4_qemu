"""Launch an independent Renode UART peer with explicit firmware and model."""
import os,struct,subprocess,time

def start_peer(renode,model,image,base,tmp,log_dir,processes,virtual_baud=None,wire_source=None,setup_commands=None,uart="usart1",name="nozzle",startup="0.01",startup_wait=None):
    tmp.mkdir();(tmp/'home/.config').mkdir(parents=True)
    pty=tmp/'uart'; data=image.read_bytes();sp,pc=struct.unpack_from('<II',data)
    if any(c.isspace() for c in str(image)): raise ValueError(name+' image path must not contain whitespace')
    resc=tmp/'peer.resc'
    wire_commands=[];endpoint=uart
    if virtual_baud:
        wire=tmp/'wire.repl'
        wire.write_text(f'serialWire: AT32.AT32VirtualSerialWire @ sysbus\n    uart: {uart}\n    baud: {virtual_baud}\n    bitsPerFrame: 10\n')
        wire_commands=[f'include @{wire_source}',f'machine LoadPlatformDescription @{wire}']
        endpoint='serialWire'
    resc.write_text('\n'.join([
        'include @scripts/load.resc',
        *wire_commands,
        f'emulation CreateUartPtyTerminal "host_link" "{pty}"',
        f'connector Connect sysbus.{endpoint} host_link',
        f'sysbus.{uart} CreateFileBackend @{tmp}/tx.bin',
        f'sysbus LoadBinary @{image} 0x{base:x}',
        f'sysbus.cpu VectorTableOffset 0x{base:x}',
        f'sysbus.cpu SP 0x{sp:x}',f'sysbus.cpu PC 0x{pc:x}',
        *(setup_commands or []),
        f'emulation RunFor "{startup}"','start','']))
    env=dict(os.environ,HOME=str(tmp/'home'),XDG_CONFIG_HOME=str(tmp/'home/.config'),TMPDIR=str(tmp))
    logfile=log_dir/(name+'-renode.log')
    if startup_wait:
        startup_wait.phase=name+' launch'
        startup_wait.check()
    with logfile.open('wb') as out:
        proc=subprocess.Popen([str(renode),'--disable-gui','--console',str(resc)],cwd=model,env=env,stdin=subprocess.PIPE,stdout=out,stderr=subprocess.STDOUT)
    processes.append(proc)
    if startup_wait:
        startup_wait.peers.append((proc,logfile))
        startup_wait.wait(name+' UART PTY',pty.exists)
        startup_wait.wait(name+' initialization',lambda:b'Starting emulation' in logfile.read_bytes())
        startup_wait.settle()
        return pty
    deadline=time.monotonic()+60
    while True:
        text=logfile.read_bytes()
        if pty.exists() and b'Starting emulation' in text: break
        if proc.poll() is not None or b'There was an error' in text or time.monotonic()>deadline:
            raise RuntimeError(name+' Renode initialization failed; inspect '+name+'-renode.log')
        time.sleep(.1)
    time.sleep(.2)
    return pty
