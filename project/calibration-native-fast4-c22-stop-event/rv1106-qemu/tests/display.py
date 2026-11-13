#!/usr/bin/env python3
"""Minimal VOP/PWM register regression. Does not claim full pixel-pipe fidelity."""
import pathlib,subprocess,sys,tempfile
qemu=str(pathlib.Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory() as tmp:
 p=subprocess.Popen([qemu,'-M','rv1106','-m','64M','-S','-display','none','-serial','null','-monitor','none','-qtest','stdio','-qtest-log',tmp+'/qtest.log'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 try:
  def cmd(s):
   p.stdin.write((s+'\n').encode());p.stdin.flush();r=p.stdout.readline().decode().strip();assert r.startswith('OK'),(s,r);return int(r.split()[1],0) if ' ' in r else None
  def rd(a):return cmd(f'readl {a:#x}')
  def wr(a,v):return cmd(f'writel {a:#x} {v:#x}')
  base=0xff990000
  assert rd(base+4)==0x2000c
  wr(base+4,0);assert rd(base+4)==0x2000c
  wr(base+0x34,0x03030301);assert rd(base+0x34)==0x301
  wr(base+0x34,0x00010000);assert rd(base+0x34)==0x300
  wr(base+0xa0,0xb00000);assert rd(base+0xa0)==0xb00000
  wr(base+0x98,480);assert rd(base+0x98)==480
  wr(base+0xa4,0x013f01df);assert rd(base+0xa4)==0x013f01df
  wr(0xff350014,600);assert rd(0xff350014)==600
  print('PASS: VOP ID, write masks, framebuffer address/stride/size, PWM register storage')
 finally:p.terminate();p.communicate(timeout=5)
