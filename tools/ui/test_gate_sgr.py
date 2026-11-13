import pathlib,subprocess,unittest
class Tests(unittest.TestCase):
 def test_sgr_exact_only(self):
  gate=pathlib.Path(__file__).with_name('backend-gate.sh.in').read_text()
  self.assertIn("sed \"s/$(printf '\\033')\\[[0-9;]*m//g\"",gate)
  base='[1970-01-01 00:00:15.200] [info] [103] Server listening on 127.0.0.1:50051'
  command=r'''sed "s/$(printf '\033')\[[0-9;]*m//g" | grep -Eq '^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\] \[info\] \[103\] Server listening on 127\.0\.0\.1:50051$' '''
  for text,ok in [(base,True),('\x1b[32m'+base+'\x1b[m',True),('echo '+base,False),('\x1b[2J'+base,False),(base.replace('[103]','[104]'),False),(base+'garbage',False)]:
   r=subprocess.run(['/bin/sh','-c',command],input=text+'\n',text=True,capture_output=True)
   self.assertEqual(r.returncode==0,ok,(text,r.stderr))
if __name__=='__main__':unittest.main()
