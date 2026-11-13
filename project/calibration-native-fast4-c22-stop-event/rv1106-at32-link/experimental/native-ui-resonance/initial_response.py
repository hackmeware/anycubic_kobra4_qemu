"""Strict source-time criteria for a single bounded native UI PID observation.

No native operation or actuator write is available. All response observations
are per-heater. A nozzle response with a cold bed is valid initial evidence,
never evidence of bed actuation, complete PID, or a frequency calibration.
"""
import hashlib
import math
import re

BASELINE_C = 25.0
CEILINGS_C = {'bed':120.0,'nozzle':260.0}
FRESH_NS = 200_000_000
CLOCK_STALL_HOST_S = 120
CLOCK_INITIAL_HOST_S = 300
FIRST_DUTY_NS = 10_000_000_000
RESPONSE_NS = 2_000_000_000
PID_LOG_DEADLINE_NS = 3_000_000_000
PID_REQUEST = re.compile(r'^\[1970-01-01 [0-9:. -]+\] \[info\] \[_handle_req_pid_calibrate\(\) in request\.cpp:1305\] req_id:[0-9]+,applink\.PidCalibrateRequest:\{heater_bed:1\}$')


class ControlledStop(Exception):
    """Expected static experiment bound, not a fault or completion claim."""


class InitialResponse:
    def __init__(self, parser):
        self.parser = parser
        self.prefix = {}
        self.heaters = {}
        self.request_line = None
        self.request_ns = None
        self.baseline_ns = None
        self.profile_verified = False
        self.intent_sha256 = None
        self.intent_ns = None
        self.responses = {name: {'gpio_duty_observed': False, 'resolved_gpio_rising_edge_observed': False, 'temperature_rise_observed': False,
            'adc_change_observed': False, 'initial_response_observed': False,
            'first_positive_duty_shared_ns': None} for name in ('bed','nozzle')}

    def arm_intent(self, sha256, source_ns, baseline_ns, now):
        if self.intent_sha256 is not None:
            if sha256!=self.intent_sha256:raise ValueError('Once-only UI PID intent changed')
            return
        if (self.request_line is not None or self.baseline_ns is None or not self.profile_verified or
                not isinstance(sha256,str) or not re.fullmatch('[a-f0-9]{64}',sha256) or
                any(type(x) is not int for x in (source_ns,baseline_ns,now)) or
                not 0<=now-source_ns<=FRESH_NS or not 0<=source_ns-baseline_ns<=FRESH_NS or
                not 0<=self.baseline_ns-baseline_ns<=FRESH_NS):
            raise ValueError('UI PID intent lacks a fresh verified dual baseline')
        self.intent_sha256=sha256;self.intent_ns=source_ns

    def console(self, text, now, *, ready=False, final=False):
        lines = text.splitlines(keepends=True)
        requests = set()
        for raw in lines:
            if not raw.endswith('\n'):
                continue
            line = raw.rstrip('\r\n')
            if '_handle_req_pid_calibrate()' in line:
                if not PID_REQUEST.fullmatch(line):
                    raise ValueError('Unrecognized or changed native UI PID request: ' + line)
                requests.add(line)
        # The original UI/application logs contain duplicate identical tail copies.
        # Distinct full native request lines, not log copies, are counted here.
        if len(requests) > 1 or self.request_line is not None and requests != {self.request_line}:
            raise ValueError('Repeated/changed native UI PID request')
        if requests and self.request_line is None:
            if (final or not ready or self.intent_ns is None or now is None or
                    not 0 <= now-self.intent_ns < PID_LOG_DEADLINE_NS or not self.profile_verified):
                raise ValueError('Native PID request without a fresh observed dual baseline and once-only UI intent')
            self.request_line = next(iter(requests))
            self.request_ns = now

    def traces(self, raw_by_heater, now, *, final=False):
        if type(now) is not int or now < 0 or now % 1000:
            raise ValueError('Missing/non-microsecond source boundary')
        parsed = {}
        for name in ('bed','nozzle'):
            raw = raw_by_heater[name]
            previous = self.prefix.get(name,b'')
            if not raw.startswith(previous):
                raise ValueError('Rewritten/truncated '+name+' thermal stream')
            summary, rows, complete = self.parser.parse_trace(raw,name,now//1000,final=final)
            # The immutable stream prefix and exact pinned topology together
            # establish model input ownership, not native interpreted temperature.
            old_rows = self.heaters.get(name,{}).get('rows',0)
            parsed[name] = (summary,rows,complete,old_rows)
        # Publish both complete current streams before evaluating a stop bound.
        self.heaters = {name:item[0] for name,item in parsed.items()}
        self.prefix = {name:item[2] for name,item in parsed.items()}
        for name,(summary,rows,complete,old_rows) in parsed.items():
            pin = 'pa0' if name=='bed' else 'pb8'
            expected_adc = 3911 if name=='bed' else 4023
            response = self.responses[name]
            for row in rows[old_rows:]:
                temperature=float(row['physical_temperature_c']); duty=float(row['last_heater_duty'])
                if temperature < BASELINE_C-1e-6:
                    raise ValueError('Unexpected below-baseline '+name+' temperature')
                if self.intent_ns is None or int(row['time_us'])*1000 < self.intent_ns:
                    if (abs(temperature-BASELINE_C)>1e-6 or duty!=0 or row[pin+'_level']!='0' or
                            int(row['published_adc_code'])!=expected_adc):
                        raise ValueError('Pre-PID heater/ADC activity: '+name)
                else:
                    # PWM duty is the completed physics-window average, not
                    # the instantaneous resolved GPIO level at a sample.
                    if row['event']=='edge' and row['changed_pin']==pin.upper() and row['changed_level']=='1':
                        response['resolved_gpio_rising_edge_observed']=True
                    if duty > 0:
                        response['gpio_duty_observed']=True
                        if response['first_positive_duty_shared_ns'] is None:
                            response['first_positive_duty_shared_ns']=now
                    response['temperature_rise_observed'] |= temperature >= BASELINE_C+0.01
                    response['adc_change_observed'] |= int(row['published_adc_code']) < expected_adc
            response['initial_response_observed'] = all(response[k] for k in
                ('resolved_gpio_rising_edge_observed','gpio_duty_observed','temperature_rise_observed','adc_change_observed'))
        if any(h.get('early_stop_required') or h['maximum_temperature_c']>=CEILINGS_C[name] for name,h in self.heaters.items()):
            raise ControlledStop('Sampled native-calibration observation temperature ceiling reached')
        if self.intent_ns is None:
            self.baseline_ns=now
        elif self.request_line is None:
            if now-self.intent_ns>=PID_LOG_DEADLINE_NS:
                raise ControlledStop('Exact native PID request log absent 3 source seconds after once-only UI confirmation; acceptance unverified')
        elif not final:
            if (now-self.request_ns>=FIRST_DUTY_NS and
                    not any(r['gpio_duty_observed'] for r in self.responses.values())):
                raise ControlledStop('No heater duty within 10 source seconds of observed PID request; response incomplete')
            for name,response in self.responses.items():
                began=response['first_positive_duty_shared_ns']
                if began is not None and now-began>=RESPONSE_NS and not response['initial_response_observed']:
                    raise ControlledStop(name+' response incomplete after 2 source seconds from first observed duty')

    def summary(self):
        return {'dual_thermal':self.heaters,'per_heater_response':self.responses,
                'native_pid_request_observed':self.request_line is not None,
                'ui_pid_intent_observed':self.intent_ns is not None,'ui_pid_intent_sha256':self.intent_sha256,
                'ui_pid_intent_source_ns':self.intent_ns,'pending_native_pid_request':self.intent_ns is not None and self.request_line is None,
                'native_pid_request_line':self.request_line,
                'native_pid_first_observed_shared_ns':self.request_ns,
                'baseline_last_observed_shared_ns':self.baseline_ns,
                'thermal_profile_verified':self.profile_verified,
                'baseline_binding_scope':'Pinned exclusive ADC topology and observed resolved GPIO/duty; final binding counters pending export',
                'native_temperature_or_target_verified':False,
                'full_pid_completion_claimed':False,'bed_actuation_inferred_from_nozzle':False,
                'response_claim_scope':'Recorded GPIO edge, later PWM duty, temperature rise and ADC change are directional evidence only',
                'causal_equation_replay_verified':False}
