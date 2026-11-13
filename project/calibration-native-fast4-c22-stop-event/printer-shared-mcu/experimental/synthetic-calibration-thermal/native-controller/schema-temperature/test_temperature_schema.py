import unittest
from temperature_schema import decode_get_status_temperatures as decode, DecodeError

def vi(n):
    n &= (1 << 64) - 1
    out = bytearray()
    while n > 127:
        out.append((n & 127) | 128); n >>= 7
    out.append(n)
    return bytes(out)

def msg(n, data):
    return vi(n * 8 + 2) + vi(len(data)) + data

def scalar(n, value):
    return vi(n * 8) + vi(value)

def response(nozzle, bed):
    return msg(1, msg(2, nozzle) + msg(3, bed))

class Tests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(decode(response(scalar(1, 205)+scalar(2, 210), scalar(1, 59)+scalar(2, 60))),
            {'nozzle': {'current': 205, 'target': 210}, 'bed': {'current': 59, 'target': 60}})
    def test_defaults(self):
        self.assertEqual(decode(response(b'', b''))['bed'], {'current': 0, 'target': 0})
    def test_signed(self):
        self.assertEqual(decode(response(scalar(1, -5), b''))['nozzle']['current'], -5)
    def test_unknown(self):
        self.assertEqual(decode(response(msg(4, b'brass')+scalar(1, 25), b''))['nozzle']['current'], 25)
    def test_rejects(self):
        cases = [b'', msg(1,b''), b'\x0a\xff', b'\x00', b'\x0f',
            response(msg(1,b''),b''), response(scalar(1,2)*2,b''),
            response(scalar(1,1<<32),b''), response(b'\x08\x80\x00',b''),
            response(b'\x08'+b'\xff'*10+b'\x01',b''), response(b'',b'')*2]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(DecodeError): decode(data)

if __name__ == '__main__': unittest.main()
