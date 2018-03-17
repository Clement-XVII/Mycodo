# coding=utf-8
# The MIT License (MIT)
#
# Copyright (c) 2015 Stephen P. Smith
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import logging
import math
import time

from .base_input import AbstractInput

# import numpy  # Used for more accurate temperature calculation


class MAX31865Sensor(AbstractInput):
    """
    A sensor support class that measures the MAX31865's humidity, temperature,
    and pressure, them calculates the altitude and dew point

    """

    def __init__(self, clk, cs, miso, mosi, device='PT100', resistor_ref=None, testing=False):
        super(MAX31865Sensor, self).__init__()
        self.logger = logging.getLogger("mycodo.inputs.max31865")
        self._temperature = None

        self.clk = clk
        self.cs = cs
        self.miso = miso
        self.mosi = mosi
        self.device = device
        self.resistor_ref = resistor_ref

        if not testing:
            import max31865
            self.sensor = max31865.max31865(self.cs, self.miso, self.mosi, self.clk)

    def __repr__(self):
        """  Representation of object """
        return "<{cls}(temperature={temp})>".format(
            cls=type(self).__name__,
            temp="{0:.2f}".format(self._temperature))

    def __str__(self):
        """ Return measurement information """
        return "Temperature: {temp}".format(
            temp="{0:.2f}".format(self._temperature))

    def __iter__(self):  # must return an iterator
        """ SensorClass iterates through live measurement readings """
        return self

    def next(self):
        """ Get next measurement reading """
        if self.read():  # raised an error
            raise StopIteration  # required
        return dict(temperature=float('{0:.2f}'.format(self._temperature)))

    @property
    def temperature(self):
        """ MAX31865 temperature in Celsius """
        if self._temperature is None:  # update if needed
            self.read()
        return self._temperature

    def get_measurement(self):
        """ Gets the measurement in units by reading the """
        self._temperature = None
        temp = self.sensor.readTemp(self.device, self.resistor_ref)
        return temp

    def read(self):
        """
        Takes a reading from the MAX31865 and updates the
        self._temperature value

        :returns: None on success or 1 on error
        """
        try:
            self._temperature = self.get_measurement()
            if self._temperature is not None:
                return  # success - no errors
        except Exception as e:
            self.logger.exception(
                "{cls} raised an exception when taking a reading: "
                "{err}".format(cls=type(self).__name__, err=e))
        return 1

    def stop_sensor(self):
        """ Called by InputController class when sensors are deactivated """
        self.sensor.cleanupGPIO()
        self.running = False


class max31865(object):
    """Reading Temperature from the MAX31865 with GPIO using
       the Raspberry Pi.  Any pins can be used.
       Numpy can be used to completely solve the Callendar-Van Dusen equation
       but it slows the temp reading down.  I commented it out in the code.
       Both the quadratic formula using Callendar-Van Dusen equation (ignoring the
       3rd and 4th degree parts of the polynomial) and the straight line approx.
       temperature is calculated with the quadratic formula one being the most accurate.
    """

    def __init__(self, csPin=8, misoPin=9, mosiPin=10, clkPin=11):
        import RPi.GPIO as GPIO
        self.GPIO = GPIO
        self.csPin = csPin
        self.misoPin = misoPin
        self.mosiPin = mosiPin
        self.clkPin = clkPin
        self.setupGPIO()

    def setupGPIO(self):
        self.GPIO.setwarnings(False)
        self.GPIO.setmode(self.GPIO.BCM)
        self.GPIO.setup(self.csPin, self.GPIO.OUT)
        self.GPIO.setup(self.misoPin, self.GPIO.IN)
        self.GPIO.setup(self.mosiPin, self.GPIO.OUT)
        self.GPIO.setup(self.clkPin, self.GPIO.OUT)

        self.GPIO.output(self.csPin, self.GPIO.HIGH)
        self.GPIO.output(self.clkPin, self.GPIO.LOW)
        self.GPIO.output(self.mosiPin, self.GPIO.LOW)

    def cleanupGPIO(self):
        self.GPIO.cleanup()

    def readTemp(self, device):
        """

        :param device: 'PT100' or 'PT1000'
        :return:
        """
        #
        # b10000000 = 0x80
        # 0x8x to specify 'write register value'
        # 0xx0 to specify 'configuration register'
        #
        # 0b10110010 = 0xB2
        # Config Register
        # ---------------
        # bit 7: Vbias -> 1 (ON)
        # bit 6: Conversion Mode -> 0 (MANUAL)
        # bit5: 1-shot ->1 (ON)
        # bit4: 3-wire select -> 1 (3 wire config)
        # bits 3-2: fault detection cycle -> 0 (none)
        # bit 1: fault status clear -> 1 (clear any fault)
        # bit 0: 50/60 Hz filter select -> 0 (60Hz)
        #
        # 0b11010010 or 0xD2 for continuous auto conversion
        # at 60Hz (faster conversion)
        #

        # one shot
        self.writeRegister(0, 0xB2)

        # conversion time is less than 100ms
        time.sleep(.1)  # give it 100ms for conversion

        # read all registers
        out = self.readRegisters(0, 8)

        conf_reg = out[0]
        print("config register byte: {}".format(conf_reg))

        [rtd_msb, rtd_lsb] = [out[1], out[2]]
        rtd_ADC_Code = ((rtd_msb << 8) | rtd_lsb) >> 1

        temp_C = self.calcPTTemp(rtd_ADC_Code, device)

        print("Temperature: {temp} C".format(temp=temp_C))

        [hft_msb, hft_lsb] = [out[3], out[4]]
        hft = ((hft_msb << 8) | hft_lsb) >> 1
        print("high fault threshold: {}".format(hft))

        [lft_msb, lft_lsb] = [out[5], out[6]]
        lft = ((lft_msb << 8) | lft_lsb) >> 1
        print("low fault threshold: {}".format(lft))

        status = out[7]
        #
        # 10 Mohm resistor is on breakout board to help
        # detect cable faults
        # bit 7: RTD High Threshold / cable fault open
        # bit 6: RTD Low Threshold / cable fault short
        # bit 5: REFIN- > 0.85 x VBias -> must be requested
        # bit 4: REFIN- < 0.85 x VBias (FORCE- open) -> must be requested
        # bit 3: RTDIN- < 0.85 x VBias (FORCE- open) -> must be requested
        # bit 2: Overvoltage / undervoltage fault
        # bits 1,0 don't care
        # print "Status byte: %x" % status

        if ((status & 0x80) == 1):
            raise FaultError("High threshold limit (Cable fault/open)")
        if ((status & 0x40) == 1):
            raise FaultError("Low threshold limit (Cable fault/short)")
        if ((status & 0x04) == 1):
            raise FaultError("Overvoltage or Undervoltage Error")

    def writeRegister(self, regNum, dataByte):
        self.GPIO.output(self.csPin, self.GPIO.LOW)

        # 0x8x to specify 'write register value'
        addressByte = 0x80 | regNum;

        # first byte is address byte
        self.sendByte(addressByte)
        # the rest are data bytes
        self.sendByte(dataByte)

        self.GPIO.output(self.csPin, self.GPIO.HIGH)

    def readRegisters(self, regNumStart, numRegisters):
        out = []
        self.GPIO.output(self.csPin, self.GPIO.LOW)

        # 0x to specify 'read register value'
        self.sendByte(regNumStart)

        for byte in range(numRegisters):
            data = self.recvByte()
            out.append(data)

        self.GPIO.output(self.csPin, self.GPIO.HIGH)
        return out

    def sendByte(self, byte):
        for bit in range(8):
            self.GPIO.output(self.clkPin, self.GPIO.HIGH)
            if (byte & 0x80):
                self.GPIO.output(self.mosiPin, self.GPIO.HIGH)
            else:
                self.GPIO.output(self.mosiPin, self.GPIO.LOW)
            byte <<= 1
            self.GPIO.output(self.clkPin, self.GPIO.LOW)

    def recvByte(self):
        byte = 0x00
        for bit in range(8):
            self.GPIO.output(self.clkPin, self.GPIO.HIGH)
            byte <<= 1
            if self.GPIO.input(self.misoPin):
                byte |= 0x1
            self.GPIO.output(self.clkPin, self.GPIO.LOW)
        return byte

    def calcPTTemp(self, RTD_ADC_Code, device='PT100', resistor_ref=None):
        # Reference Resistor
        if resistor_ref:
            R_REF = resistor_ref
        elif device == 'PT100':
            R_REF = 400.0
        elif device == 'PT1000':
            R_REF = 4000.0
        else:
            return

        Res0 = 100.0  # Resistance at 0 degC for 400ohm R_Ref
        a = .00390830
        b = -.000000577500
        # c = -4.18301e-12 # for -200 <= T <= 0 (degC)
        c = -0.00000000000418301
        # c = 0 # for 0 <= T <= 850 (degC)
        print("RTD ADC Code: {}".format(RTD_ADC_Code))
        Res_RTD = (RTD_ADC_Code * R_REF) / 32768.0  # PT100 Resistance
        print("{dev} Resistance: {res} ohms".format(dev=device, res=Res_RTD))
        #
        # Callendar-Van Dusen equation
        # Res_RTD = Res0 * (1 + a*T + b*T**2 + c*(T-100)*T**3)
        # Res_RTD = Res0 + a*Res0*T + b*Res0*T**2 # c = 0
        # (c*Res0)T**4 - (c*Res0)*100*T**3
        # + (b*Res0)*T**2 + (a*Res0)*T + (Res0 - Res_RTD) = 0
        #
        # quadratic formula:
        # for 0 <= T <= 850 (degC)
        temp_C = -(a * Res0) + math.sqrt(a * a * Res0 * Res0 - 4 * (b * Res0) * (Res0 - Res_RTD))
        temp_C = temp_C / (2 * (b * Res0))
        temp_C_line = (RTD_ADC_Code / 32.0) - 256.0
        # removing numpy.roots will greatly speed things up
        # temp_C_numpy = numpy.roots([c*Res0, -c*Res0*100, b*Res0, a*Res0, (Res0 - Res_RTD)])
        # temp_C_numpy = abs(temp_C_numpy[-1])
        print("Straight Line Approx. Temp: {} degC".format(temp_C_line))
        print("Callendar-Van Dusen Temp (degC > 0): {} degC".format(temp_C))
        # print "Solving Full Callendar-Van Dusen using numpy: %f" %  temp_C_numpy
        if (temp_C < 0):  # use straight line approximation if less than 0
            # Can also use python lib numpy to solve cubic
            # Should never get here in this application
            temp_C = (RTD_ADC_Code / 32) - 256
        return temp_C


class FaultError(Exception):
    pass


if __name__ == "__main__":
    import max31865

    csPin = 8
    misoPin = 9
    mosiPin = 10
    clkPin = 11
    max = max31865.max31865(csPin, misoPin, mosiPin, clkPin)
    tempC = max.readTemp('PT100')
    max.cleanupGPIO()