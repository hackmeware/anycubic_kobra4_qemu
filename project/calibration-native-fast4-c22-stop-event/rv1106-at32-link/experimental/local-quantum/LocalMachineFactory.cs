using System;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
namespace Antmicro.Renode.Peripherals.SchedulerExperiment {
 public class LocalMachineFactory:IDoubleWordPeripheral,IKnownSize {
 public long Size{get{return 4;}}public void Reset(){}public uint ReadDoubleWord(long o){return 0;}public void WriteDoubleWord(long o,uint v){}
 public void CreateNozzle(){EmulationManager.Instance.CurrentEmulation.AddMachine(new Machine(true),"nozzle");}
 public void Check(string path,bool local){var em=EmulationManager.Instance.CurrentEmulation;IMachine main,motor,nozzle;em.TryGetMachineByName("main",out main);em.TryGetMachineByName("motor",out motor);em.TryGetMachineByName("nozzle",out nozzle);
 if(!Object.ReferenceEquals(main.LocalTimeSource,em.MasterTimeSource)||!Object.ReferenceEquals(motor.LocalTimeSource,em.MasterTimeSource))throw new Exception("Unexpected main/motor source");
 if(Object.ReferenceEquals(nozzle.LocalTimeSource,em.MasterTimeSource)==local)throw new Exception("Unexpected nozzle source");
 if(!Object.ReferenceEquals(nozzle.LocalTimeSource.Domain,em.MasterTimeSource.Domain))throw new Exception("Different time domain");
 File.WriteAllText(path,"master="+em.MasterTimeSource.Quantum+"\nnozzle="+nozzle.LocalTimeSource.Quantum+"\nnozzle_type="+nozzle.LocalTimeSource.GetType().Name+"\nsame_domain=true\n");}
 }
}
