// SPDX-License-Identifier: MIT
// Component only: no native attachment, clocks, sample fabrication or source mutation.
using System;
using Antmicro.Renode.Peripherals.PrinterNozzle;
using Antmicro.Renode.Peripherals.SensorCrossBoard;

namespace Antmicro.Renode.Peripherals.SensorGpioBridgePrinterNozzle
{
    // Specialized to the LIS2DW12 preview/commit extension, not a generic SPI
    // serializer. The predecessor's byte Transmit API is independently preserved.
    public sealed class GpioMode3Lis2dw12Bridge : IPeripheral, IDisposable
    {
        public GpioMode3Lis2dw12Bridge(AT32GPIO gpio, TimedLis2dw12 sensor)
        {
            if(gpio == null || sensor == null) throw new ArgumentNullException("gpio/sensor");
            this.gpio = gpio; this.sensor = sensor;
            gpio.RegisterWritten += ObserveWrite;
            gpio.ResetCompleted += Reset;
            Reset();
        }

        public bool Selected { get; private set; }
        public int ReceivedBits { get; private set; }
        public ulong CompletedBytes { get; private set; }
        public ulong PreparedReadBytes { get; private set; }
        public ulong AbortedPartialBytes { get; private set; }
        public string Fault { get; private set; }

        // Transport reset does not reset the sensor, its FIFO or its source.
        // If CS is low, require deassertion before accepting another transaction.
        public void Reset()
        {
            Abort();
            Fault = null;
            CompletedBytes = PreparedReadBytes = AbortedPartialBytes = 0;
            idleSeen = (gpio.ReadDoubleWord(0xC) & Cs) != 0;
        }

        public void Dispose()
        {
            if(disposed) return;
            gpio.RegisterWritten -= ObserveWrite;
            gpio.ResetCompleted -= Reset;
            Abort(); disposed = true;
        }

        private bool PinsConfigured()
        {
            var high = gpio.ReadDoubleWord(4);
            // Push-pull ordinary outputs only; no unmodeled AF/open-drain bus.
            foreach(var pin in new[]{12, 13, 15})
            {
                var config = (high >> (4 * (pin - 8))) & 15;
                if((config & 3) == 0 || (config >> 2) != 0) return false;
            }
            var miso = (high >> 24) & 15;
            return miso == 4 || miso == 8; // Floating or pull-configured input.
        }

        private void ObserveWrite(long offset, uint before, uint after)
        {
            if(disposed) return;
            if(!PinsConfigured())
            {
                Abort(); idleSeen = false; return;
            }
            var csHigh = (after & Cs) != 0;
            if(csHigh)
            {
                Abort(); idleSeen = true; return;
            }
            if(Fault != null) return; // Explicit transport Reset is required.
            if(!Selected)
            {
                if(!idleSeen || (before & Cs) == 0) return;
                if((before & Clock) == 0 || (after & Clock) == 0)
                {
                    Fail(new InvalidOperationException("Mode 3 requires SCLK high before CS assertion."));
                    return;
                }
                sensor.OnGPIO(0, false);
                Selected = true; idleSeen = false; haveCommand = reading = false;
                ReceivedBits = 0; receive = 0; armed = false;
                return; // CS-asserting write never counts as a clock edge.
            }
            if(((before ^ after) & Clock) == 0) return;
            try
            {
                if((after & Clock) == 0)
                {
                    if(armed) throw new InvalidOperationException("Repeated leading edge.");
                    if(ReceivedBits == 0)
                    {
                        reservation = haveCommand && reading ? sensor.PrepareReadByte() : null;
                        response = reservation == null ? (byte)0xFF : reservation.Value;
                        if(reservation != null) PreparedReadBytes++;
                    }
                    gpio.OnGPIO(14, (response & (1 << (7 - ReceivedBits))) != 0);
                    armed = true;
                }
                else
                {
                    if(!armed) throw new InvalidOperationException("Trailing edge without leading edge.");
                    receive = (byte)((receive << 1) | ((after & Mosi) != 0 ? 1 : 0));
                    armed = false; ReceivedBits++;
                    if(ReceivedBits != 8) return;
                    if(!haveCommand)
                    {
                        sensor.Transmit(receive); reading = (receive & 0x80) != 0; haveCommand = true;
                    }
                    else if(!reading) sensor.Transmit(receive);
                    else { sensor.CommitReadByte(reservation); reservation = null; }
                    CompletedBytes++; ReceivedBits = 0; receive = 0;
                    // Hold final MISO bit until next falling edge or deselection.
                }
            }
            catch(Exception error) { Fail(error); }
        }

        private void Fail(Exception error)
        {
            Fault = error.GetType().Name + ": " + error.Message;
            Abort(); idleSeen = false;
            throw new InvalidOperationException("GPIO SPI bridge failed: " + Fault, error);
        }

        private void Abort()
        {
            if(Selected && (ReceivedBits != 0 || armed)) AbortedPartialBytes++;
            sensor.FinishTransmission();
            reservation = null;
            Selected = false; haveCommand = reading = armed = false;
            ReceivedBits = 0; receive = 0; response = 0xFF;
            gpio.ReleasePin(14);
        }

        private const uint Cs = 1u << 12, Clock = 1u << 13, Mosi = 1u << 15;
        private readonly AT32GPIO gpio;
        private readonly TimedLis2dw12 sensor;
        private bool idleSeen, haveCommand, reading, armed, disposed;
        private byte receive, response;
        private TimedLis2dw12.ReadReservation reservation;
    }
}
