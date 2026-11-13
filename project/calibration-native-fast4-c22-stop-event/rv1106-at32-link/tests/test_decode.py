#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from decode_frames import crc16,frames
class DecoderTests(unittest.TestCase):
    def test_plain(self):
        data=bytes.fromhex('0b105f33937c840b61da7e')
        self.assertEqual(crc16(data[:-3]),0x61da)
        self.assertEqual(list(frames(data))[0]['transform'],'plain')
    def test_wrapped_request(self):
        f=list(frames(bytes.fromhex('68587a7828c44784')))
        self.assertEqual(f[0]['decoded_hex'],'08100100285e9f7e')
        self.assertEqual(f[0]['xor_byte'],0x78)
    def test_wrapped_startup(self):
        self.assertEqual(list(frames(bytes.fromhex('5b75ed5502d0a9')))[0]['decoded_hex'],'07105c00abc27e')
    def test_bad_crc(self):
        self.assertEqual(list(frames(bytes.fromhex('68587a7828c44785'))),[])
    def test_noise_and_offsets(self):
        f=list(frames(bytes.fromhex('ac2505060000000068587a7828c44784')))
        self.assertEqual(len(f),1);self.assertEqual(f[0]['offset'],8)
if __name__=='__main__':unittest.main()
