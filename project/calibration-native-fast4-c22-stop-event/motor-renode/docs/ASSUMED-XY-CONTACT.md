# Explicit centered XY contact scenario

Source evidence: at32-renode/docs/NATIVE-MOTION-CONFIG.md and firmware-evidence/native-motion-config.json. Original host software limits are X -18.5 to 280 mm and Y -7.5 to 272.5 mm, with 39 mm/revolution. These are not measured hard-stop positions.

The opt-in test scenario assumes the physical travel span equals that configured span and starts each carriage at its midpoint. Relative compliant stops are therefore X +/-149.25 mm and Y +/-140 mm. Initial physical placement is a scenario assumption, not an inferred real position. No origin or homed coordinate is assigned to firmware. Existing generic stiffness 10 N m/rad and damping 0.01 N m s/rad remain illustrative, not measured.

Use --motor-setup-commands rv1106-at32-link/tests/assumed-centered-xy-contact.commands with --shared-mcus --motor-plant electromechanical-driver. This applies before original firmware runs. The driver/rotor parameters remain the documented defaults. Contact torque changes integrated motion/back-EMF and sensed ADC currents; only original firmware may generate diagnostic events. No GPIO is directly driven from geometry.

No Z contact/probe model is provided. Native X/Y homing and detector behavior remain to be validated. Successful generic contact equations, native readiness, or RPC acknowledgment are insufficient. A no-contact run is a useful negative control: detector completion without actual contact must not be labeled mechanically validated homing.
