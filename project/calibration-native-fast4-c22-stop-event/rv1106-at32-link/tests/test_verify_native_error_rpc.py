import importlib.util,pathlib,sys,unittest
S=pathlib.Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(S));from verify_native_error_rpc import verify

def capture(pb=b'',status=b'0'):
 def frame(t,f,p):return len(p).to_bytes(3,'big')+bytes([t,f])+b'\0\0\0\1'+p
 d=frame(0,0,b'\0'+len(pb).to_bytes(4,'big')+pb)+frame(1,5,b'grpc-status\x01'+status)
 return 'BEGIN\n'+'\n'.join(f'{i:07o} '+' '.join(f'{b:03o}' for b in d[i:i+16]) for i in range(0,len(d),16))+'\nDONE\n'
class Tests(unittest.TestCase):
 def test_acceptance_not_completion(self):
  r=verify(capture(),'BEGIN','DONE');self.assertTrue(r['api_accepted']);self.assertFalse(r['physical_completion_proven'])
 def test_native_error(self):self.assertFalse(verify(capture(bytes.fromhex('0a0408ffff03')),'BEGIN','DONE')['api_accepted'])
 def test_transport_error(self):self.assertFalse(verify(capture(status=b'1'),'BEGIN','DONE')['api_accepted'])
 def test_echo_not_marker(self):self.assertEqual(verify('echo BEGIN\necho DONE\n','BEGIN','DONE')['status'],'pending_begin')
 def test_incomplete_response(self):
  with self.assertRaises(ValueError):verify('BEGIN\n0000000 000 000 020\nDONE\n','BEGIN','DONE')
 def test_pending_end(self):self.assertEqual(verify('BEGIN\n','BEGIN','DONE')['status'],'pending_end')
if __name__=='__main__':unittest.main()
