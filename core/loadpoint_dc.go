package core

// ChargingTypeDC marks a loadpoint as a current-regulated DC charger
const ChargingTypeDC = "dc"

// minDcChargeVoltage is the minimum plausible DC charging voltage. Measurements
// below this value (idle station, ramp-up) are treated as not available.
const minDcChargeVoltage = 50

// isDC returns true if the loadpoint controls a current-regulated DC charger
func (lp *Loadpoint) isDC() bool {
	return lp.ChargingType == ChargingTypeDC
}

// GetChargingType returns the charging type ("ac" or "dc")
func (lp *Loadpoint) GetChargingType() string {
	if lp.isDC() {
		return ChargingTypeDC
	}
	return "ac"
}

// GetDcMaxVoltage returns the maximum DC charger voltage
func (lp *Loadpoint) GetDcMaxVoltage() float64 {
	return lp.DcMaxVoltage
}

// effectiveVoltage returns the voltage for converting power to current and vice versa.
// For AC loadpoints this is the global nominal grid voltage. For DC loadpoints it is
// the live measured charging voltage, falling back to the configured maximum charger
// voltage. The fallback is conservative: assuming the highest possible voltage yields
// the lowest current for a given power budget, hence power limits cannot be exceeded.
func (lp *Loadpoint) effectiveVoltage() float64 {
	if !lp.isDC() {
		return Voltage
	}

	if u := lp.maxChargeVoltage(); u >= minDcChargeVoltage {
		return u
	}

	return lp.DcMaxVoltage
}

// maxChargeVoltage returns the maximum measured charge voltage or 0 if not available
func (lp *Loadpoint) maxChargeVoltage() float64 {
	if lp.chargeVoltages == nil {
		return 0
	}
	return max(lp.chargeVoltages[0], lp.chargeVoltages[1], lp.chargeVoltages[2])
}

// currentToPower converts current to power. For AC loadpoints this assumes nominal
// grid voltage on the given number of phases, for DC loadpoints the actual charging
// voltage applies and phases are ignored.
func (lp *Loadpoint) currentToPower(current float64, phases int) float64 {
	if lp.isDC() {
		return current * lp.effectiveVoltage()
	}
	return currentToPower(current, phases)
}

// powerToCurrent converts power to current. For AC loadpoints this assumes nominal
// grid voltage on the given number of phases, for DC loadpoints the actual charging
// voltage applies and phases are ignored.
func (lp *Loadpoint) powerToCurrent(power float64, phases int) float64 {
	if lp.isDC() {
		return power / lp.effectiveVoltage()
	}
	return powerToCurrent(power, phases)
}
