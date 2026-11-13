// SPDX-License-Identifier: MIT
// Additive physical-only observer. Fixed synthetic-functional minimum bed at -10 mm.
using System;
using System.Globalization;
using System.IO;
using System.Text;
using Antmicro.Renode.Core;
namespace Antmicro.Renode.Peripherals.AT32
{
    public sealed class PassivePhysicalStateTrace : IPeripheral, IGPIOReceiver, IDisposable
    {
        public PassivePhysicalStateTrace(IMachine machine, GenericStepperElectromechanical plant, AT32Timer tmr8)
        {
            this.machine=machine; this.plant=plant;
            // Construct AFTER plant: never disconnect or replace its trigger receiver.
            tmr8.TriggerOutput.Connect(this,0);
        }
        public void Reset() { } // Neither physical state nor evidence counters are reset.
        public void ConfigureLongRun(int maximumRows)
        {
            if(started)throw new InvalidOperationException("Configure before Start");
            if(maximumRows<1||maximumRows>100000)throw new ArgumentOutOfRangeException("maximumRows");
            maximum=maximumRows;
        }
        public void Start(string path)
        {
            if(started)throw new InvalidOperationException("Single-use observer");
            started=true;
            try
            {
                writer=new StreamWriter(new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.Read),new UTF8Encoding(false));
                string header="sequence,observation_time_s";
                foreach(var a in new[]{"x","y","z"})header+=","+a+"_state_time_s,"+a+"_angle_rad,"+a+"_relative_mm,"+a+"_velocity_rad_s,"+a+"_contact_torque_nm,"+a+"_bridge_enabled";
                writer.WriteLine(header+",z_bed_clearance_mm,z_compression_mm,z_contact_force_n,z_contact_nonzero");writer.Flush();
                Capture();
            }
            catch(Exception e){Fail(e);throw;}
        }
        public void OnGPIO(int number,bool value)
        {
            if(number!=0||!value||writer==null)return;
            TriggerEdges++;
            try
            {
                double source=plant.GetLastIntegrationTimeSeconds(2);
                if(!Finite(source)||source<lastTrigger)throw new InvalidOperationException("Invalid/regressing physical source time");
                if(lastTrigger>=0&&source>lastTrigger){double dt=source-lastTrigger;minTrigger=Math.Min(minTrigger,dt);maxTrigger=Math.Max(maxTrigger,dt);}
                lastTrigger=source;
                if(source-lastSample<0.01){DecimatedEdges++;return;}
                lastSample=source;
                if(RowsWritten>=(ulong)maximum){CapacityReached=true;DroppedRows++;return;}
                Capture();
            }
            catch(Exception e){DroppedRows++;Fail(e);}
        }
        private void Capture()
        {
            var row=new StringBuilder();row.Append(RowsWritten.ToString(CultureInfo.InvariantCulture));
            Add(row,machine.ElapsedVirtualTime.TimeElapsed.TotalSeconds);
            double z=0,torque=0;
            for(int a=0;a<3;a++)
            {
                double state=plant.GetLastIntegrationTimeSeconds(a);
                Add(row,state);Add(row,plant.GetAngleRadians(a));
                double travel=plant.GetRelativeTravelMillimeters(a);Add(row,travel);
                Add(row,plant.GetVelocityRadiansPerSecond(a));
                double contact=plant.GetContactTorqueNewtonMeters(a);Add(row,contact);
                row.Append(plant.GetBridgeEnabled(a)?",1":",0");
                if(a==2){z=travel;torque=contact;lastSample=state;}
            }
            Add(row,z+10);Add(row,Math.Max(0,-10-z));Add(row,Math.Max(0,torque)/(0.008/(2*Math.PI)));
            row.Append(torque!=0?",1":",0");
            writer.WriteLine(row.ToString());writer.Flush();RowsWritten++;
        }
        private static void Add(StringBuilder row,double value)
        {if(!Finite(value))throw new InvalidOperationException("Non-finite physical snapshot");row.Append(',').Append(value.ToString("R",CultureInfo.InvariantCulture));}
        private static bool Finite(double x)=>!Double.IsNaN(x)&&!Double.IsInfinity(x);
        private void Fail(Exception e){ErrorCount++;LastError=e.GetType().Name+": "+e.Message;Stop();}
        public void Stop()
        {
            Stopped=true;var w=writer;writer=null;
            if(w!=null)try{w.Dispose();}catch(Exception e){ErrorCount++;LastError=e.GetType().Name+": "+e.Message;}
        }
        public void Dispose(){Stop();}
        public void WriteStatus(string path)
        {
            if(!Stopped)throw new InvalidOperationException("Stop before exporting final status");
            // Status, too, must be new. Failure propagates and invalidates the run.
            using(var w=new StreamWriter(new FileStream(path,FileMode.CreateNew,FileAccess.Write,FileShare.Read),new UTF8Encoding(false)))
            {
                w.WriteLine("{\"schema\":\"cold-physical-v1\",\"rows_written\":"+RowsWritten+",\"dropped_rows\":"+DroppedRows+",\"error_count\":"+ErrorCount+",\"last_error\":\""+Escape(LastError)+"\",\"capacity_reached\":"+(CapacityReached?"true":"false")+",\"stopped\":true,\"trigger_edges\":"+TriggerEdges+",\"decimated_edges\":"+DecimatedEdges+",\"min_observed_trigger_interval_s\":"+(Double.IsPositiveInfinity(minTrigger)?"null":minTrigger.ToString("R",CultureInfo.InvariantCulture))+",\"max_observed_trigger_interval_s\":"+maxTrigger.ToString("R",CultureInfo.InvariantCulture)+"}");w.Flush();
            }
        }
        private static string Escape(string s)
        {var b=new StringBuilder();foreach(char c in s){if(c=='"'||c=='\\')b.Append('\\').Append(c);else if(c<32)b.Append("\\u").Append(((int)c).ToString("x4"));else b.Append(c);}return b.ToString();}
        public ulong RowsWritten{get;private set;}public ulong DroppedRows{get;private set;}public ulong ErrorCount{get;private set;}
        public ulong TriggerEdges{get;private set;}public ulong DecimatedEdges{get;private set;}
        public bool CapacityReached{get;private set;}public bool Stopped{get;private set;}
        public string LastError{get;private set;}="";
        private readonly IMachine machine;private readonly GenericStepperElectromechanical plant;
        private StreamWriter writer;private bool started;
        private int maximum=6000;
        private double lastSample=-1,lastTrigger=-1,minTrigger=Double.PositiveInfinity,maxTrigger=0;
    }
}
