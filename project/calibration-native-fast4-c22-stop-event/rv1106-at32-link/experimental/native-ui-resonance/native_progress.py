"""Passive exact-source native target/stage evidence, never a command or success oracle."""
import datetime
import math
import re

LINE=re.compile(r"^\[(1970-01-01 [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3})\] \[info\] \[(.*?)\] (.*)$")
TARGET=re.compile(r"Heater '(extruder|heater_bed)' target temperature updated to ([0-9]+(?:\.[0-9]+)?)$")
PID=re.compile(r"script:PID_CALIBRATE HEATER=(extruder|heater_bed) TARGET=([0-9]+(?:\.[0-9]+)?) WRITE_FILE=0,is_notice:true,is_error:true$")
STAGE=re.compile(r"work_flow_type:([A-Z_]+\([0-9]+\)),work_flow_state_type:([A-Z_]+\([0-9]+\)),work_state_type:([A-Z_]+\([0-9]+\)),progress:([0-9]+)$")
SOURCE='refresh_workflow_state() in ets/480*320/guide_page/guide_pid_calibrate_widget.cpp:126'
CAPS={'extruder':250.0,'heater_bed':110.0}

class NativeProgress:
    def __init__(self):
        self.seen=set();self.targets={h:None for h in CAPS};self.target_lines={h:None for h in CAPS}
        self.last_time={};self.events=[];self.first_extruder_pid=False;self.stages=[]
    def observe(self,text,intent_observed):
        for raw in text.splitlines(keepends=True):
            if not raw.endswith('\n'):continue
            line=raw.rstrip('\r\n')
            relevant=('target temperature updated to' in line or 'script:PID_CALIBRATE ' in line or 'work_flow_state_type:' in line)
            if not relevant or line in self.seen:continue
            match=LINE.fullmatch(line)
            if not match:raise ValueError('Malformed native calibration evidence: '+line)
            stamp,source,body=match.groups();datetime.datetime.strptime(stamp,'%Y-%m-%d %H:%M:%S.%f')
            if 'target temperature updated to' in body:
                parsed=TARGET.fullmatch(body)
                if source!='199' or not parsed:raise ValueError('Unknown native heater/target/source: '+line)
                heater,value=parsed.groups();value=float(value)
                if not math.isfinite(value) or not 0<=value<=CAPS[heater]:raise ValueError('Native target outside admitted observation envelope: '+line)
                if value>0 and not intent_observed:raise ValueError('Positive native target before once-only UI intent')
                key=('target',heater)
                if key in self.last_time and stamp<=self.last_time[key]:raise ValueError('Conflicting/backwards native target update: '+line)
                if heater=='extruder' and value>0 and not self.first_extruder_pid:raise ValueError('Extruder target without known initial PID230 command')
                self.last_time[key]=stamp;self.targets[heater]=value;self.target_lines[heater]=line
                self.events.append({'kind':'native_target','heater':heater,'target_c':value,'line':line,'source_timestamp':stamp})
            elif 'script:PID_CALIBRATE ' in body:
                parsed=PID.fullmatch(body)
                if source!='161' or not parsed or not intent_observed:raise ValueError('Unrecognized native PID command: '+line)
                heater,value=parsed.groups();value=float(value)
                if not math.isfinite(value) or not 0<=value<=CAPS[heater]:raise ValueError('Native PID target outside admitted observation envelope')
                key=('pid',heater)
                if key in self.last_time and stamp<=self.last_time[key]:raise ValueError('Conflicting/backwards native PID command')
                if heater=='extruder' and not self.first_extruder_pid:
                    if value!=230:raise ValueError('Initial extruder PID command must be exactly230')
                    self.first_extruder_pid=True
                self.last_time[key]=stamp;self.events.append({'kind':'native_pid_command','heater':heater,'target_c':value,'line':line,'source_timestamp':stamp})
            else:
                # Unknown later UI phase source is retained as evidence, never asserted as success.
                parsed=STAGE.fullmatch(body)
                if not parsed:raise ValueError('Malformed native workflow record: '+line)
                event={'line':line,'source':source,'source_timestamp':stamp,'known_pid_widget_source':source==SOURCE}
                self.stages.append(event)
            self.seen.add(line)
            if len(self.seen)>512:raise ValueError('Native calibration evidence event bound exceeded')
    def summary(self):
        return {'native_targets_c':dict(self.targets),'native_target_lines':dict(self.target_lines),
                'native_target_events':list(self.events),'native_stage_records':list(self.stages),
                'native_first_extruder_pid_230_observed':self.first_extruder_pid,
                'native_target_zero_observed':{h:self.targets[h]==0 for h in CAPS},
                'native_target_envelope_c':dict(CAPS),'native_calibration_completion_mechanically_certified':False,
                'native_target_zero_proves_heater_off_or_cooling':False}
