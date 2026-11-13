import unittest
from ui_evidence import parse
RUN='ui-12345678'
def native(source,msg,sec=1,level='info'):
 return f'[2026-11-12 00:00:{sec:02}.000] [{level}] [{source}] {msg}\n'
def ready():
 return ('C18_UI_GATE_BEGIN run='+RUN+'\n'+native('103','Server listening on 127.0.0.1:50051')+native('527','Printer is ready at 1.0.',2)+f'C18_UI_BACKEND_VERIFIED run={RUN} main_pid=3 start_ticks=1 socket_inode=4\nC18_UI_LAUNCH_BEGIN run={RUN}\nC18_UI_LAUNCHED run={RUN} ui_pid=8\nCOLD_UI_STARTUP_COMMANDS_DONE\n'+native('_check_channel() in applink_client.cpp:194','channel:main_channel,state:GRPC_CHANNEL_READY(2)',3)+native('_check_main_channel() in applink_client.cpp:153','main channel is ready',4)+native('operator()() in request.cpp:1523','req_id:1,applink.PrinterStateResponse:{state:ready,state_message:Printer is ready}',5))
class Tests(unittest.TestCase):
 def test_ready(self):
  r=parse(ready(),RUN);self.assertTrue(r['ready']);self.assertTrue(r['ui_connection_ready'])
 def test_empty(self):self.assertFalse(parse('',RUN)['ui_connection_ready'])
 def test_echo(self):self.assertFalse(parse("printf 'C18_UI_GATE_BEGIN run="+RUN+"'\n",RUN)['begin'])
 def test_partial(self):self.assertFalse(parse('C18_UI_GATE_BEGIN run='+RUN,RUN)['begin'])
 def test_wrong_run(self):
  with self.assertRaises(ValueError):parse(ready(),RUN+'x')
 def test_duplicate(self):
  with self.assertRaises(ValueError):parse(ready()+f'C18_UI_LAUNCHED run={RUN} ui_pid=8\n',RUN)
 def test_sgr(self):self.assertTrue(parse('\x1b[32m'+ready()+'\x1b[0m',RUN)['ready'])
 def test_control(self):
  for c in ['\x1b[2J','\x08','\x7f','\r']:
   with self.assertRaises(ValueError):parse(c+ready(),RUN)
 def test_optional_before(self):
  error=native('218','Unable to read config file /app/etc/avata_main_mutable.cfg',1,'error')
  r=parse(error+ready(),RUN);self.assertEqual(len(r['native_errors']),1);self.assertEqual(len(r['startup_limitations']),1);self.assertFalse(r['fault_observed'])
 def test_optional_after(self):
  r=parse(ready()+native('218','Unable to read config file /app/etc/avata_main_mutable.cfg',6,'error'),RUN);self.assertTrue(r['fault_observed'])
 def test_wrong_source(self):self.assertTrue(parse(native('219','Unable to read config file /app/etc/avata_main_mutable.cfg',1,'error'),RUN)['fault_observed'])
 def test_changed_text(self):self.assertTrue(parse(native('218','Unable to read config file /app/etc/other.cfg',1,'error'),RUN)['fault_observed'])
 def test_critical(self):self.assertTrue(parse(native('218','Unable to read config file /app/etc/avata_main_mutable.cfg',1,'critical'),RUN)['fault_observed'])
 def test_regression(self):
  with self.assertRaises(ValueError):parse(ready()+native('_check_channel() in applink_client.cpp:194','channel:main_channel,state:GRPC_CHANNEL_SHUTDOWN(4)',6),RUN)
 def test_unrecognized_printer(self):
  with self.assertRaises(ValueError):parse(ready()+native('wrong','req_id:1,applink.PrinterStateResponse:{state:ready,state_message:Printer is ready}',6),RUN)
if __name__=='__main__':unittest.main()
