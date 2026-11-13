#!/usr/bin/env python3
import sys,struct,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from inspect_motion_queue import inspect
from decode_motor_frames import crc16
def frame(c,p):
 b=bytes([126,0,c,len(p)])+p;return b+crc16(b).to_bytes(2,'little')
class Test(unittest.TestCase):
 def test_queue(self):
  d=frame(4,b'\0\0')+frame(5,struct.pack('<BIHhI',0,120000,3200,-1,123))
  r=inspect(d);self.assertEqual(r['totals']['x']['signed_steps_with_known_direction'],3200);self.assertEqual(r['events'][1]['requested_travel_mm'],39);self.assertEqual(r['events'][1]['interval_add_ticks'],-1)
 def test_unknown_direction(self):
  r=inspect(frame(5,struct.pack('<BIHhI',1,1,80,0,0)));self.assertEqual(r['totals']['y']['steps_with_unknown_direction'],80);self.assertNotIn('requested_travel_mm',r['events'][0])
 def test_bad(self):
  for b in [frame(5,b'\0'),frame(4,b'\0\2'),frame(17,b'\x05'),b'bad']:
   with self.assertRaises(ValueError):inspect(b)
if __name__=='__main__':unittest.main()
