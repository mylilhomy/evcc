package core

import (
	"testing"

	"github.com/evcc-io/evcc/util"
	"github.com/stretchr/testify/assert"
)

func TestEffectiveVoltage(t *testing.T) {
	Voltage = 230

	tc := []struct {
		name           string
		chargingType   string
		dcMaxVoltage   float64
		chargeVoltages []float64
		expected       float64
	}{
		{"ac default", "", 0, nil, 230},
		{"ac ignores measurement", "", 0, []float64{400, 0, 0}, 230},
		{"dc with measurement", ChargingTypeDC, 1000, []float64{412, 0, 0}, 412},
		{"dc without measurement", ChargingTypeDC, 1000, nil, 1000},
		{"dc idle station reports zero", ChargingTypeDC, 1000, []float64{0, 0, 0}, 1000},
		{"dc below plausible voltage", ChargingTypeDC, 1000, []float64{12, 0, 0}, 1000},
		{"dc high voltage vehicle", ChargingTypeDC, 1000, []float64{920, 0, 0}, 920},
	}

	for _, tc := range tc {
		t.Run(tc.name, func(t *testing.T) {
			lp := NewLoadpoint(util.NewLogger("foo"), nil)
			lp.ChargingType = tc.chargingType
			lp.DcMaxVoltage = tc.dcMaxVoltage
			lp.chargeVoltages = tc.chargeVoltages

			assert.Equal(t, tc.expected, lp.effectiveVoltage())
		})
	}
}

func TestDcPowerCurrentConversion(t *testing.T) {
	Voltage = 230

	// ac regression: conversion identical to package helpers
	ac := NewLoadpoint(util.NewLogger("foo"), nil)
	assert.Equal(t, currentToPower(16, 3), ac.currentToPower(16, 3))
	assert.Equal(t, powerToCurrent(11040, 3), ac.powerToCurrent(11040, 3))
	assert.InDelta(t, 11040.0, ac.currentToPower(16, 3), 1e-9)

	// dc: P = U_dc * I, phases ignored
	dc := NewLoadpoint(util.NewLogger("foo"), nil)
	dc.ChargingType = ChargingTypeDC
	dc.DcMaxVoltage = 1000
	dc.chargeVoltages = []float64{400, 0, 0}

	assert.InDelta(t, 40000.0, dc.currentToPower(100, 3), 1e-9, "100A at 400V must be 40kW regardless of phases")
	assert.InDelta(t, 100.0, dc.powerToCurrent(40000, 3), 1e-9, "40kW at 400V must be 100A regardless of phases")
	assert.InDelta(t, dc.powerToCurrent(40000, 1), dc.powerToCurrent(40000, 3), 1e-9, "dc conversion must ignore phases")

	// dc fallback: conservative, highest voltage yields lowest current
	dc.chargeVoltages = nil
	assert.InDelta(t, 40.0, dc.powerToCurrent(40000, 3), 1e-9, "without measurement 40kW must convert at 1000V to 40A")

	// dc at high vehicle voltage: same power budget, lower current
	dc.chargeVoltages = []float64{800, 0, 0}
	assert.InDelta(t, 50.0, dc.powerToCurrent(40000, 3), 1e-9)
}

func TestDcDisablesPhaseSwitching(t *testing.T) {
	lp := NewLoadpoint(util.NewLogger("foo"), nil)
	lp.ChargingType = ChargingTypeDC

	assert.False(t, lp.hasPhaseSwitching(), "dc loadpoint must never switch phases")
}

func TestDcEffectiveStepPower(t *testing.T) {
	Voltage = 230

	lp := NewLoadpoint(util.NewLogger("foo"), nil)
	lp.ChargingType = ChargingTypeDC
	lp.DcMaxVoltage = 1000
	lp.chargeVoltages = []float64{500, 0, 0}

	assert.InDelta(t, 500.0, lp.EffectiveStepPower(), 1e-9, "dc step power must be voltage per amp")
}
