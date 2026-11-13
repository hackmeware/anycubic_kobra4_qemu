"""Offline emitted ARM-byte interpreter + strict captured streaming regressions.

No native MCU run, real socket, QEMU Linux or firmware execution. The existing
ARM instruction interpreter executes the actual emitted ELF with mocked syscalls.
"""
import importlib.util
import pathlib
import struct
import unittest
import tempfile

HERE=pathlib.Path(__file__).resolve().parent

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

m=load(HERE/'status_snapshot.py','snapshot_test')
c=load(HERE/'controller.py','snapshot_controller')
arm=load(m.ROOT/'rv1106-at32-link/experimental/stream-end-probe/arm_fixture.py','snapshot_arm')
CAPTURE=(HERE/'streaming-status-review/r2-full-stream.http2.bin').read_bytes()
FIRST=CAPTURE[:368]
PAIR=CAPTURE[:568]
PB1=(HERE/'streaming-status-review/r2-message-1.protobuf.bin')
# Filenames are recorded by the extraction worker; actual captures remain bytes.
PAYLOADS=m.snapshot_protobufs(PAIR,c.ready.decode_headers)
CANCEL=m.frame(3,0,1,(8).to_bytes(4,'big'))
ELF=m.build_snapshot(m.request_packet())


def header():
    return m.frame(1,4,1,b'\x88\x00\x0ccontent-type\x10application/grpc')

def grpc(pb):return b'\0'+len(pb).to_bytes(4,'big')+pb

def stream(messages):return header()+m.frame(0,0,1,b''.join(grpc(pb) for pb in messages))


class Machine(arm.Machine):
    def __init__(self,*args,shutdown_result=0,close_result=0,**kwargs):
        super().__init__(*args,**kwargs)
        self.shutdown_result,self.close_result=shutdown_result,close_result
        self.local_shutdown,self.local_close=False,False
    def syscall(self):
        r=self.reg
        if r[7]==293:
            self.syscalls.append(293)
            assert r[0]==self.socket_result and r[1]==2
            self.local_shutdown=True
            r[0]=self.shutdown_result & 0xffffffff
        elif r[7]==6:
            self.syscalls.append(6)
            assert r[0]==self.socket_result
            self.local_close=True
            r[0]=self.close_result & 0xffffffff
        else:super().syscall()


def execute(data,**kwargs):
    machine=Machine(ELF,[data],**kwargs)
    machine.run()
    return machine


class EmittedClientTests(unittest.TestCase):
    def test_actual_r2_two_messages_and_explicit_cancel_close(self):
        machine=execute(CAPTURE)
        self.assertEqual(machine.exit_code,20)
        self.assertEqual(bytes(machine.stdout),PAIR)
        self.assertTrue(bytes(machine.sent).endswith(CANCEL))
        self.assertEqual(bytes(machine.sent).count(CANCEL),1)
        self.assertEqual(machine.syscalls[-3:],[293,6,1])
        self.assertTrue(machine.local_shutdown and machine.local_close)
        self.assertGreater(sum(map(len,machine.chunks)),0) # Later3 messages never read.
        self.assertEqual(c.temperature.decode_get_status_temperatures(PAYLOADS[0])['nozzle']['current'],0)
        self.assertEqual(c.temperature.decode_get_status_temperatures(PAYLOADS[1]),
                         {'nozzle':{'current':25,'target':0},'bed':{'current':25,'target':0}})

    def test_every_byte_fragmented_and_partial_syscalls(self):
        machine=Machine(ELF,[bytes([x]) for x in PAIR],send_limit=1,write_limit=1,
                        read_eintr=2,send_eintr=2,write_eintr=2)
        machine.run()
        self.assertEqual(machine.exit_code,20)
        self.assertEqual(bytes(machine.stdout),PAIR)
        self.assertTrue(bytes(machine.sent).endswith(CANCEL))

    def test_grpc_envelope_and_payload_across_individual_data_frames(self):
        data=header()+b''.join(m.frame(0,0,1,bytes([x])) for x in grpc(PAYLOADS[0])+grpc(PAYLOADS[1]))
        machine=execute(data)
        self.assertEqual(machine.exit_code,20)
        self.assertEqual(m.snapshot_protobufs(bytes(machine.stdout),c.ready.decode_headers),PAYLOADS)

    def test_both_messages_in_one_data_frame_allowed_but_extra_rejected(self):
        self.assertEqual(execute(stream(PAYLOADS)).exit_code,20)
        for data in (stream(PAYLOADS+[PAYLOADS[0]]),stream(PAYLOADS)+m.frame(0,0,1,b'\0')):
            # Extra separate frames are not read after exact pair; extra bytes
            # inside the pair's last frame are rejected, never silently sliced.
            if data==stream(PAYLOADS)+m.frame(0,0,1,b'\0'):
                self.assertEqual(execute(data).exit_code,20)
            else:self.assertEqual(execute(data).exit_code,m.MALFORMED)
        data=header()+m.frame(0,0,1,grpc(PAYLOADS[0])+grpc(PAYLOADS[1])+b'\0')
        self.assertEqual(execute(data).exit_code,m.MALFORMED)

    def test_first_only_waits_not_success_and_eof_truncation_is_failure(self):
        machine=Machine(ELF,[FIRST])
        with self.assertRaises(arm.WouldBlock):machine.run()
        self.assertIsNone(machine.exit_code)
        self.assertFalse(machine.local_close)
        self.assertNotIn(CANCEL,bytes(machine.sent))
        self.assertEqual(execute(FIRST,eof=True).exit_code,m.EOF)
        for end in (1,8,100,367,369,567):
            self.assertNotEqual(execute(PAIR[:end],eof=True).exit_code,20)

    def test_reset_end_and_invalid_envelopes(self):
        for data in (header()+m.frame(3,0,1,bytes(4)),header()+m.frame(0,1,1,grpc(PAYLOADS[0])),
                     header()+m.frame(0,0,1,b'\1\0\0\0\0'),
                     header()+m.frame(0,0,1,b'\0'+(65537).to_bytes(4,'big'))):
            self.assertNotEqual(execute(data,eof=True).exit_code,20)

    def test_cancel_send_shutdown_close_failures_never_success(self):
        # Reference run identifies bytes sent before the CANCEL attempt.
        before_cancel=len(execute(PAIR).sent)-len(CANCEL)
        for kwargs in ({'send_error':-32,'send_error_after':before_cancel},
                       {'shutdown_result':-5},{'close_result':-5},
                       {'send_limit':1,'send_error':-32,'send_error_after':before_cancel+5},
                       {'send_error':-32,'send_error_after':0}, {'connect_result':-111}):
            machine=execute(PAIR,**kwargs)
            self.assertEqual(machine.exit_code,m.IO_ERROR,kwargs)
        failed=execute(PAIR,send_error=-32,send_error_after=before_cancel)
        self.assertFalse(failed.local_shutdown or failed.local_close)

    def test_headers_continuation_padding_and_control_frames(self):
        initial=header();payload=initial[9:]
        h=m.frame(1,0,1,payload[:3])+m.frame(9,4,1,payload[3:])
        data=h+m.frame(0,8,1,b'\2'+grpc(PAYLOADS[0])+grpc(PAYLOADS[1])+b'xx')
        machine=execute(data)
        self.assertEqual(machine.exit_code,20)
        self.assertEqual(m.snapshot_protobufs(bytes(machine.stdout),c.ready.decode_headers),PAYLOADS)
        bad=m.frame(1,0,1,payload[:3])+m.frame(6,0,0,bytes(8))+m.frame(9,4,1,payload[3:])
        self.assertEqual(execute(bad).exit_code,m.MALFORMED)


class HostValidationTests(unittest.TestCase):
    def test_http_errors_duplicates_trailers_reject_even_if_client_canceled(self):
        for prefix in (m.frame(1,4,1,b'\x8e\0\x0ccontent-type\x10application/grpc'),
                       header()+header(),m.frame(1,4,1,b'\x88'),
                       m.frame(1,4,1,b'\x88\0\x0ccontent-type\x10application/grpc\0\x0bgrpc-status\x011')):
            with self.assertRaises(ValueError):m.snapshot_protobufs(prefix+m.frame(0,0,1,b''.join(map(grpc,PAYLOADS))),c.ready.decode_headers)

    def test_not_complete_rpc_and_capture_budget_failures(self):
        for data in (FIRST,PAIR[:-1],CAPTURE,PAIR+b'\0',stream(PAYLOADS+[b'']),
                     header()+m.frame(7,0,0,bytes(8)),b'x'*(m.MAX_CAPTURE+1)):
            with self.assertRaises(ValueError):m.snapshot_protobufs(data,c.ready.decode_headers)
        with self.assertRaises(ValueError):c.xyz.unary_protobuf(PAIR)

    def test_actual_r2_timeout_is_not_reclassified_as_success(self):
        import json
        run=m.ROOT/'runs/native-nozzle-230-synthetic-r2'
        request=json.loads((run/'thermal-observation.json').read_text())['requests'][1]
        with self.assertRaises(ValueError):
            c.verify_capture((run/'console.bin').read_text(errors='replace'),request)

    def test_selection_is_sequence_not_temperature_and_both_messages_validate(self):
        def wrap(data):
            def od(data):
                return ''.join(f'{i:07o} '+' '.join(f'{v:03o}' for v in data[i:i+16])+'\n' for i in range(0,len(data),16))+f'{len(data):07o}\n'
            request={'begin':'B','end':'E','method':'GetStatus'}
            text='B\nREADY_CLIENT_STATUS=20\nREADY_RAW_BEGIN\n'+od(data)+'READY_RAW_END\nGRPC_PROBE_TRANSPORT_EXIT=20\nGRPC_PROBE_DONE\nE\n'
            return c.verify_capture(text,request)
        result=wrap(stream(PAYLOADS[::-1]))
        self.assertEqual(result['native_temperatures']['nozzle']['current_c'],0)
        self.assertEqual(result['selected_native_message_index'],2)
        self.assertEqual(len(result['captured_native_messages']),2)
        for messages in ([b'\xff',PAYLOADS[1]],[PAYLOADS[0],b'\xff']):
            with self.assertRaises(ValueError):wrap(stream(messages))

    def test_original_unary_readiness_elf_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            c.prepare_request(pathlib.Path(tmp),'ready','offline','PrinterState')
            self.assertEqual((pathlib.Path(tmp)/'thermal-ready.elf').read_bytes(),
                             (m.ROOT/'runs/native-nozzle-230-synthetic-r2/thermal-ready.elf').read_bytes())

    def test_exact_packet_only(self):
        for packet in (m.request_packet()+b'\0',m.request_packet().replace(b'GetStatus',b'PrintInfo')):
            with self.assertRaises(ValueError):m.build_snapshot(packet)


if __name__=='__main__':unittest.main()
