"""Single-entry-per-heater cache for identical immutable trace byte values.

Integration candidate only. Never reads files, changes clocks, substitutes
measurements, relaxes limits or treats stat/size metadata as byte equality.
The injected parser remains authoritative on every changed trace. Dynamic
boundary and final-line requirements run on every hit. Caller outputs are
copied, so mutation cannot corrupt subsequent evidence assessments.
"""
class ExactTraceCache:
    def __init__(self, parser):
        self.parser = parser
        self.entries = {}
        self.hits = self.misses = 0

    def parse_trace(self, raw, heater, boundary_us, final=False):
        # Restrict caching to the concrete types used by the existing observer.
        # Unusual inputs retain the original parser's exact behavior.
        if type(raw) is not bytes or type(boundary_us) is not int or heater not in ('bed', 'nozzle'):
            return self.parser.parse_trace(raw, heater, boundary_us, final=final)
        entry = self.entries.get(heater)
        if entry is None or entry[0] != raw:
            self.misses += 1
            result = self.parser.parse_trace(raw, heater, boundary_us, final=final)
            summary, rows, complete = result
            self.entries[heater] = (raw, dict(summary, latest=dict(summary['latest'])),
                                    [dict(row) for row in rows], complete)
            return result
        self.hits += 1
        _, summary, rows, complete = entry
        self.parser.require(raw and (not final or raw.endswith(b'\n')),
                            heater + ' missing/truncated final CSV')
        latest = summary['latest_source_us']
        self.parser.require(latest <= boundary_us,
                            heater + ' telemetry ahead of confirmed source boundary')
        self.parser.require(boundary_us-latest <= self.parser.MAX_AGE_US,
                            heater + ' stale physical trace')
        return (dict(summary, latest=dict(summary['latest']), source_age_us=boundary_us-latest),
                [dict(row) for row in rows], complete)
