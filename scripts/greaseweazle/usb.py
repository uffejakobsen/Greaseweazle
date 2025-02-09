# greaseweazle/usb.py
#
# Written & released by Keir Fraser <keir.xen@gmail.com>
#
# This is free and unencumbered software released into the public domain.
# See the file COPYING for more details, or visit <http://unlicense.org>.

import struct
from greaseweazle import version
from greaseweazle.flux import Flux

## Control-Path command set
class ControlCmd:
    ClearComms      = 10000
    Normal          =  9600


## Command set
class Cmd:
    GetInfo         =  0
    Seek            =  1
    Side            =  2
    SetParams       =  3
    GetParams       =  4
    Motor           =  5
    ReadFlux        =  6
    WriteFlux       =  7
    GetFluxStatus   =  8
    GetIndexTimes   =  9
    Select          = 10
    # Bootloader specific:
    Update          =  1


## Command responses/acknowledgements
class Ack:
    Okay            = 0
    BadCommand      = 1
    NoIndex         = 2
    NoTrk0          = 3
    FluxOverflow    = 4
    FluxUnderflow   = 5
    Wrprot          = 6
    Max             = 6


## Cmd.{Get,Set}Params indexes
class Params:
    Delays          = 0


## CmdError: Encapsulates a command acknowledgement.
class CmdError(Exception):

    str = [ "Okay", "Bad Command", "No Index", "Track 0 not found",
            "Flux Overflow", "Flux Underflow", "Disk is Write Protected" ]

    def __init__(self, cmd, code):
        self.cmd = cmd
        self.code = code

    def __str__(self):
        if self.code <= Ack.Max:
            return self.str[self.code]
        return "Unknown Error (%u)" % self.code


class Unit:

    ## Unit information, instance variables:
    ##  major, minor: Greaseweazle firmware version number
    ##  max_index:    Maximum index timings for Cmd.ReadFlux
    ##  max_cmd:      Maximum Cmd number accepted by this unit
    ##  sample_freq:  Resolution of all time values passed to/from this unit

    ## Unit(ser):
    ## Accepts a Pyserial instance for Greaseweazle communications.
    def __init__(self, ser):
        self.ser = ser
        self.reset()
        # Copy firmware info to instance variables (see above for definitions).
        self._send_cmd(struct.pack("3B", Cmd.GetInfo, 3, 0))
        x = struct.unpack("<4BI24x", self.ser.read(32))
        (self.major, self.minor, self.max_index,
         self.max_cmd, self.sample_freq) = x
        # Check whether firmware is in update mode: limited command set if so.
        self.update_mode = (self.max_index == 0)
        if self.update_mode:
            self.update_jumpered = (self.sample_freq & 1)
            del self.max_index
            del self.sample_freq
            return
        # We are running main firmware: Check whether an update is needed.
        # We can use only the GetInfo command if the firmware is out of date.
        self.update_needed = (version.major != self.major
                              or version.minor != self.minor)
        if self.update_needed:
            return
        # Initialise the delay properties with current firmware values.
        self._send_cmd(struct.pack("4B", Cmd.GetParams, 4, Params.Delays, 10))
        (self._select_delay, self._step_delay,
         self._seek_settle_delay, self._motor_delay,
         self._auto_off_delay) = struct.unpack("<5H", self.ser.read(10))


    ## reset:
    ## Resets communications with Greaseweazle.
    def reset(self):
        self.ser.reset_output_buffer()
        self.ser.baudrate = ControlCmd.ClearComms
        self.ser.baudrate = ControlCmd.Normal
        self.ser.reset_input_buffer()


    ## _send_cmd:
    ## Send given command byte sequence to Greaseweazle.
    ## Raise a CmdError if command fails.
    def _send_cmd(self, cmd):
        self.ser.write(cmd)
        (c,r) = struct.unpack("2B", self.ser.read(2))
        assert c == cmd[0]
        if r != 0:
            raise CmdError(c, r)


    ## seek:
    ## Seek the selected drive's heads to the specified track (cyl, side).
    def seek(self, cyl, side):
        self._send_cmd(struct.pack("3B", Cmd.Seek, 3, cyl))
        self._send_cmd(struct.pack("3B", Cmd.Side, 3, side))


    ## drive_select:
    ## Select/deselect the drive.
    def drive_select(self, state):
        self._send_cmd(struct.pack("3B", Cmd.Select, 3, int(state)))


    ## drive_motor:
    ## Turn the selected drive's motor on/off.
    def drive_motor(self, state):
        self._send_cmd(struct.pack("3B", Cmd.Motor, 3, int(state)))


    ## _get_index_times:
    ## Get index timing values for the last .read_track() command.
    def _get_index_times(self, nr):
        self._send_cmd(struct.pack("4B", Cmd.GetIndexTimes, 4, 0, nr))
        x = struct.unpack("<%dI" % nr, self.ser.read(4*nr))
        return x


    ## update_firmware:
    ## Update Greaseweazle to the given new firmware.
    def update_firmware(self, dat):
        self._send_cmd(struct.pack("<2BI", Cmd.Update, 6, len(dat)))
        self.ser.write(dat)
        (ack,) = struct.unpack("B", self.ser.read(1))
        return ack


    ## _decode_flux:
    ## Decode the Greaseweazle data stream into a list of flux samples.
    def _decode_flux(self, dat):
        flux = []
        dat_i = iter(dat)
        try:
            while True:
                i = next(dat_i)
                if i < 250:
                    flux.append(i)
                elif i == 255:
                    val =  (next(dat_i) & 254) >>  1
                    val += (next(dat_i) & 254) <<  6
                    val += (next(dat_i) & 254) << 13
                    val += (next(dat_i) & 254) << 20
                    flux.append(val)
                else:
                    val = (i - 249) * 250
                    val += next(dat_i) - 1
                    flux.append(val)
        except StopIteration:
            pass
        assert flux[-1] == 0
        return flux[:-1]


    ## _encode_flux:
    ## Convert the given flux timings into an encoded data stream.
    def _encode_flux(self, flux):
        dat = bytearray()
        for val in flux:
            if val == 0:
                pass
            elif val < 250:
                dat.append(val)
            else:
                high = val // 250
                if high <= 5:
                    dat.append(249+high)
                    dat.append(1 + val%250)
                else:
                    dat.append(255)
                    dat.append(1 | (val<<1) & 255)
                    dat.append(1 | (val>>6) & 255)
                    dat.append(1 | (val>>13) & 255)
                    dat.append(1 | (val>>20) & 255)
        dat.append(0) # End of Stream
        return dat


    ## _read_track:
    ## Private helper which issues command requests to Greaseweazle.
    def _read_track(self, nr_revs):

        # Request and read all flux timings for this track.
        dat = bytearray()
        self._send_cmd(struct.pack("3B", Cmd.ReadFlux, 3, nr_revs+1))
        while True:
            dat += self.ser.read(1)
            dat += self.ser.read(self.ser.in_waiting)
            if dat[-1] == 0:
                break

        # Check flux status. An exception is raised if there was an error.
        self._send_cmd(struct.pack("2B", Cmd.GetFluxStatus, 2))

        return dat


    ## read_track:
    ## Read and decode flux and index timings for the current track.
    def read_track(self, nr_revs, nr_retries=5):

        retry = 0
        while True:
            try:
                dat = self._read_track(nr_revs)
            except CmdError as error:
                # An error occurred. We may retry on transient overflows.
                if error.code == Ack.FluxOverflow and retry < nr_retries:
                    retry += 1
                else:
                    raise error
            else:
                # Success!
                break

        # Decode the flux list and read the index-times list.
        flux_list = self._decode_flux(dat)
        index_list = self._get_index_times(nr_revs+1)

        # Clip the initial partial revolution.
        to_index = index_list[0]
        for i in range(len(flux_list)):
            to_index -= flux_list[i]
            if to_index < 0:
                flux_list[i] = -to_index
                flux_list = flux_list[i:]
                break
        if to_index >= 0:
            # We ran out of flux.
            flux_list = []
        index_list = index_list[1:]

        # Success: Return the requested full index-to-index revolutions.
        return Flux(index_list, flux_list, self.sample_freq)


    ## write_track:
    ## Write the given flux stream to the current track via Greaseweazle.
    def write_track(self, flux_list, nr_retries=5):

        # Create encoded data stream.
        dat = self._encode_flux(flux_list)
        
        retry = 0
        while True:
            try:
                # Write the flux stream to the track via Greaseweazle.
                self._send_cmd(struct.pack("<2BIB", Cmd.WriteFlux, 7, 0, 1))
                self.ser.write(dat)
                self.ser.read(1) # Sync with Greaseweazle
                self._send_cmd(struct.pack("2B", Cmd.GetFluxStatus, 2))
            except CmdError as error:
                # An error occurred. We may retry on transient underflows.
                if error.code == Ack.FluxUnderflow and retry < nr_retries:
                    retry += 1
                else:
                    raise error
            else:
                # Success!
                break


    ##
    ## Delay-property public getters and setters:
    ##  select_delay:      Delay (usec) after asserting drive select
    ##  step_delay:        Delay (usec) after issuing a head-step command
    ##  seek_settle_delay: Delay (msec) after completing a head-seek operation
    ##  motor_delay:       Delay (msec) after turning on drive spindle motor
    ##  auto_off_delay:    Timeout (msec) since last command upon which all
    ##                     drives are deselected and spindle motors turned off
    ##

    def _set_delays(self):
        self._send_cmd(struct.pack("<3B5H", Cmd.SetParams,
                                   3+5*2, Params.Delays,
                                   self._select_delay, self._step_delay,
                                   self._seek_settle_delay,
                                   self._motor_delay, self._auto_off_delay))

    @property
    def select_delay(self):
        return self._select_delay
    @select_delay.setter
    def select_delay(self, select_delay):
        self._select_delay = select_delay
        self._set_delays()

    @property
    def step_delay(self):
        return self._step_delay
    @step_delay.setter
    def step_delay(self, step_delay):
        self._step_delay = step_delay
        self._set_delays()

    @property
    def seek_settle_delay(self):
        return self._seek_settle_delay
    @seek_settle_delay.setter
    def seek_settle_delay(self, seek_settle_delay):
        self._seek_settle_delay = seek_settle_delay
        self._set_delays()

    @property
    def motor_delay(self):
        return self._motor_delay
    @motor_delay.setter
    def motor_delay(self, motor_delay):
        self._motor_delay = motor_delay
        self._set_delays()

    @property
    def auto_off_delay(self):
        return self._auto_off_delay
    @auto_off_delay.setter
    def auto_off_delay(self, auto_off_delay):
        self._auto_off_delay = auto_off_delay
        self._set_delays()

# Local variables:
# python-indent: 4
# End:
