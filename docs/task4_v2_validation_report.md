# Task 4: Buildings.city V2.0 Pipeline Validation Report

> **Date:** 2026-07-27
> **Upstream:** `City-Syntax/buildings.city` commit `fde303a` (2026-05-16, MIT)
> **epinterface PyPI:** 1.5.0 (upstream pins 1.0.5)
> **Target E+ version:** 26.1.0 (not installed in this environment)
> **Our baseline:** 52-grid simulation matrix v0, E+ 26.1.0, zero failures

---

## Step 0: Environment Inventory

| Item | Status | Detail |
|---|---|---|
| Python | 3.11.15 | OK |
| pip | 24.0 | OK |
| EnergyPlus | **NOT INSTALLED** | Gates ⑤⑥ blocked; user confirmation pending (per §0-2 rule) |
| 52-grid v0 files | Present | `outputs/simulation/matrix_v0_monthly_eui.csv` (52 cells, 0 failures) |
| Upstream clone | `/root/upstream_bc/` | commit `fde303a`, `simulation-service/` verified |
| Shanghai weather | Present | CSWD 583620 EPW + DDY + STAT in `weather/` |

---

## Gate ① — epinterface Installation

**Verdict: 🟡 Conditional GREEN — installs, but requires 3 workarounds**

### Steps taken

1. `pip install epinterface` → FAILED (esoreader / tinynumpy wheel build errors)
   - Root cause: `setuptools==68.1.2` lacks `install_layout` attribute needed by `setup.py` packages
   - Fix: `pip install --upgrade setuptools` (68.1.2 → 83.0.0)
2. Retry → FAILED (`Cannot uninstall packaging 24.0, RECORD file not found`)
   - Root cause: Debian system `packaging` has no pip RECORD
   - Fix: `pip install --ignore-installed packaging epinterface`
3. Post-install: `import epinterface` succeeds, but `model.build()` → `RuntimeError: Prisma client has not been generated`
   - Fix: `epinterface prisma generate` (one-time code generation step)

### Observations

- **Version mismatch**: upstream `requirements.txt` pins `epinterface==1.0.5`; PyPI latest is 1.5.0. The Prisma dependency is new in 1.5.0 (1.0.5 likely doesn't need it).
- **archetypal 2.18.9** imports with UserWarning about missing E+ but does not crash.
- `epinterface.__version__` attribute missing — must use `importlib.metadata.version('epinterface')`.

### Time spent: ~15 min

---

## Gate ② — EnergyPlus Version Gap

**Verdict: 🟡 Conditional GREEN — patchable in principle, untested**

### Analysis (code reading, no live test)

The upstream IDF generation chain:
```
templates.json → epinterface ZoneComponent → Model.build() → IDF (v22.2) → patch → IDF (v24.2)
```

`make_idf_energyplus_24_2_compatible()` (template_builder.py:517-529) does two string replacements:
1. `"ZoneAveraged"` → `"EnclosureAveraged"` (field rename in E+ 23.1)
2. Version string `22.2` → `24.2` (regex, first occurrence)

For Shanghai pipeline (E+ 26.1.0), an analogous `make_idf_energyplus_26_1_compatible()` would be needed. Scope:
- Known: version string `24.2` → `26.1`
- Unknown: whether E+ 24.2→26.1 introduced IDD schema changes (renamed fields, new required fields, deprecated objects) beyond a version string swap. The existing 52-grid IDFs were written directly for v26.1 via eppy + Energy+.idd 26.1.

### Risk

If the IDD changes between 24.2 and 26.1 are non-trivial (e.g., `HVACTEMPLATE:ZONE:IDEALLOADSAIRSYSTEM` field order or new required fields), the patch approach breaks. Upstream uses `HVACTEMPLATE:*` objects while our 52-grid uses raw `ZONEHVAC:IDEALLOADSAIRSYSTEM` — the expansion behavior of HVAC templates varies across E+ versions.

### Blocker: Cannot test without E+ 26.1.0 installed.

---

## Gate ③ — HVAC Modeling Consistency

**Verdict: ✅ GREEN**

### Comparison

| Aspect | Upstream (template_builder) | Our 52-grid (shoebox.py) |
|---|---|---|
| HVAC type | Ideal Loads (via `HVACTEMPLATE:ZONE:IDEALLOADSAIRSYSTEM`) | Ideal Loads (direct `ZONEHVAC:IDEALLOADSAIRSYSTEM`) |
| Heating | Optional (`cop_heat=None` → no heating) | Always present, COP-adjusted |
| Cooling | Always present, COP-adjusted | Always present, COP-adjusted |
| Setpoint schedule | **Constant 24h** (t_heat/t_cool flat) | **Setback** (occupied vs unoccupied, e.g., 18/15°C heating, 26/28°C cooling) |
| HVAC availability | **Always on** (no schedule) | On/off schedule tied to occupancy |
| Ventilation | Mechanical, per-person + per-area | Mechanical, per-person + per-area |
| DHW | Separate `DHWComponent` with COP | Separate `WaterUse:Equipment` with COP |

### Assessment

Both pipelines use the same fundamental HVAC model (ideal loads air system). The differences are tuning-level:
- Setback temperatures and HVAC availability schedules affect energy use significantly but are **configurable** — `templates.json` schedules can encode setback profiles by using temperature schedule values.
- The `HVACTEMPLATE` vs direct `ZONEHVAC` difference: E+ expands HVAC templates into raw objects during preprocessing. The expanded result should be functionally equivalent.

**No architectural incompatibility.**

---

## Gate ④ — Weather Swappability

**Verdict: ✅ GREEN (with minor packaging requirement)**

### Evidence

- `template_builder.py` line 493: `weather: str | Path` parameter, not hardcoded.
- `generate_idfs.py` line 27: `--weather` CLI flag, default is Singapore but overridable.
- Singapore hardcoding (lat/lon/timezone/elevation) exists ONLY in `idf_writer.py:1375-1389` (`_update_site_location()`), which is the per-building urban simulation path, **not** the template generation path.

### Caveat

epinterface 1.5.0 `BaseWeather.fetch_weather()` requires the weather file as a `.zip` archive containing `.epw` + `.ddy` (line 79: `if not self.Weather.suffix == ".zip": raise NotAZipError()`). Our Shanghai CSWD files are unpacked. **Fix is trivial**: `zip CHN_SH_Shanghai.583620_CSWD.zip *.epw *.ddy` — tested, works.

### Shanghai CSWD weather availability: ✓

Station 583620 (Baoshan), both CSWD and TMYx.2011-2025 variants available with EPW + DDY + STAT.

---

## Gate ⑤ — Office Single-Type IDF Generation

**Verdict: 🔴 RED — blocked on EnergyPlus installation**

### Part A: Template JSON field gap analysis

Created `test_office_template.json` with GB 50189-2015 office parameters. Time: **~15 min**.

**All 22 `SimulationTemplateParameters` fields mapped:**

| Field | Value used | GB 50189 source | Notes |
|---|---|---|---|
| `wwr` | 0.40 | Table 3.3.2 (hot-summer/cold-winter, shape coefficient ≤0.40) | Direct |
| `u_wall` | 0.60 | Table 3.3.1-3 (HSCW zone, Class B) | Direct |
| `u_roof` | 0.55 | Table 3.3.1-3 | Direct |
| `u_floor` | 1.50 | Not in GB 50189 envelope table | **Estimated**, ground slab, may need owner review |
| `u_win` | 2.80 | Table 3.3.2 (wwr 0.3-0.4, HSCW) | Direct |
| `shgc` | 0.40 | Table 3.3.2 (wwr 0.3-0.4, HSCW) | Direct |
| `tvis` | 0.50 | **Not in GB 50189** | Glazing product data needed |
| `ach` | 0.50 | Common assumption for office | Not a GB parameter |
| `occ` | 0.10 | GB 50189 附录B (10 m²/person → 0.1 person/m²) | Direct |
| `epd` | 15.0 | GB 50189 附录B (office, 15 W/m²) | Direct |
| `lpd` | 9.0 | GB 50189 Table 6.3.3 (office ≤9 W/m²) | Direct |
| `hw_lppd` | 5.0 | **Not directly in GB 50189** | Cross-ref needed (GB 50015?) |
| `cop_cool` | 3.5 | GB 50189 Table 4.2.15 (water-cooled chiller, COP≥5.0; air-cooled ≥3.0 for ideal loads approximation) | Needs owner decision |
| `cop_heat` | 2.8 | GB 50189 Table 4.2.17 (ASHP, HSCW zone) | Needs owner review |
| `cop_dhw` | 1.0 | **Not in GB 50189** | Defaulted to electric resistance equivalent |
| `t_heat` | 18.0 | GB 50189 §5.2 (18°C for office) | Direct |
| `t_cool` | 26.0 | GB 50189 §5.2 (26°C for office) | Direct |
| `dhw_supply_temp` | 60.0 | GB 50015 standard practice | Not a GB 50189 parameter |
| `dhw_inlet_temp` | 10.0 | Shanghai winter ground water temp estimate | Regional engineering data |
| `fresh_air_per_person` | 0.008333 | GB 50189 附录B (30 m³/h/person = 0.00833 m³/s/person) | Unit conversion needed |
| `fresh_air_per_floor_area` | 0.0 | Set to 0 (per-person mode) | OK |
| `schedules` | 6 profiles | Custom weekday/weekend for occ/lighting/equipment | GB 50189 附录C has reference profiles |

**Fields where GB 50189 gives no direct value (must cross-reference or estimate):**
1. `tvis` — visible transmittance of glazing, product-specific
2. `hw_lppd` — hot water demand per person per day, needs GB 50015
3. `cop_dhw` — DHW system COP, not a building energy efficiency standard parameter
4. `u_floor` — ground slab U-value, not in GB 50189 envelope prescriptive tables
5. `ach` — infiltration rate, typically from GB 50736 or pressure test standards

### Part B: IDF generation attempt

**Three sequential failures before reaching IDD blocker:**

1. **Prisma client not generated** → fixed with `epinterface prisma generate`
2. **Weather not in .zip format** → fixed by packaging EPW+DDY into zip
3. **`archetypal.IDF` requires EnergyPlus IDD file** → **HARD BLOCKER, no workaround**

Error chain on attempt 3:
```
model.build() → IDF.__init__() → idd_info → _read_idf()
→ iddname → file_version.current_idd_path
→ valid_idd_paths[self.dash] → KeyError: '22-2-0'
```

The `valid_idd_paths` property scans the filesystem for `Energy+.idd` files from E+ installations. With no E+ installed, the dict is empty. **This is a structural dependency of the archetypal library — IDF generation cannot proceed without an E+ installation providing the IDD.**

### Contrast with our 52-grid pipeline

Our `shoebox.py` uses `eppy.modeleditor.IDF` which also needs an IDD, but eppy allows explicit `IDF.setiddname(path)` — we can point to a standalone IDD file without a full E+ installation. The upstream's archetypal dependency adds a harder coupling.

---

## Gate ⑥ — Result Comparison with 52-Grid

**Verdict: ⬜ NOT TESTED — depends on Gate ⑤**

### Baseline data available for future comparison

52-grid v0 office annual EUI (E+ 26.1.0, CSWD Shanghai):

| Height bin | Floors | Annual EUI (kWh/m²/yr) |
|---|---|---|
| low | 2 | 92.1 |
| multi | 5 | 93.6 |
| high | 15 | 94.3 |
| supertall | 35 | 94.5 |

When Gate ⑤ is unblocked (E+ installed), the comparison target is office multi (5F) at **93.6 kWh/m²/yr** — the upstream test used the same floor count and similar geometry.

---

## Summary Table

| Gate | Topic | Verdict | Blocker |
|---|---|---|---|
| ① | epinterface install | 🟡 Conditional GREEN | 3 workarounds needed; version mismatch (1.0.5 vs 1.5.0) |
| ② | E+ version gap | 🟡 Conditional GREEN | Untested; 24.2→26.1 patch scope unknown |
| ③ | HVAC consistency | ✅ GREEN | None |
| ④ | Weather swappable | ✅ GREEN | Weather must be zipped (trivial) |
| ⑤ | Office IDF generation | 🔴 RED (blocked) | E+ not installed → archetypal IDD lookup fails |
| ⑥ | EUI comparison | ⬜ NOT TESTED | Depends on ⑤ |

---

## Cost Estimate: Self-Built → Upstream Switch

If Gates ⑤⑥ are eventually cleared (E+ installed, IDF generation works, EUI in range):

| Work item | Estimate |
|---|---|
| Write `make_idf_energyplus_26_1_compatible()` patch | 2-4 hours (depends on IDD delta 24.2→26.1) |
| Convert 14 archetypes × 4 height bins to `templates.json` format | 1-2 days (parameter table transcription + schedule encoding) |
| Integrate weather zip packaging into pipeline | 0.5 hours |
| Version-pin epinterface (test 1.0.5 vs 1.5.0 compat) | 2-4 hours |
| Regression test: compare upstream-generated vs 52-grid monthly EUI for all 52 cells | 1-2 days |
| **Total** | **~3-5 days** |

If keeping self-built pipeline (only borrowing `templates.json` format):

| Work item | Estimate |
|---|---|
| Rewrite `config/simulation_matrix.yaml` parameter tables to `templates.json` schema | 1 day |
| No code changes to `shoebox.py` | 0 |
| **Total** | **~1 day** |

---

## Recommendation (Evidence Only — Owner Decides)

**The validation is incomplete.** Two of six gates could not be tested due to missing EnergyPlus. The findings so far:

1. **The upstream pipeline has a harder E+ coupling than our self-built one.** archetypal's IDD discovery requires a full E+ installation at IDF generation time; eppy (our current tool) allows standalone IDD file paths. This matters for CI/CD and reproducibility.

2. **The `templates.json` format is clean and useful regardless of pipeline choice.** The 22-field `SimulationTemplateParameters` schema maps well to GB 50189 parameters. Borrowing this format for our parameter tables is independently valuable.

3. **HVAC and weather are compatible.** No architectural barriers exist for simulating Shanghai buildings with the upstream's ideal-loads approach.

4. **Version friction is real.** epinterface 1.0.5 vs 1.5.0, E+ 22.2→24.2→26.1, Prisma code generation — each is individually solvable but collectively adds integration risk.

**To complete this validation**, the owner should:
1. Confirm E+ 26.1.0 installation
2. Re-run Gate ⑤ (IDF generation with Shanghai weather + GB parameters)
3. Run Gate ⑥ (simulate and compare monthly EUI against 52-grid)
4. Then decide: full switch vs parameter-format-only adoption

---

_Generated by Claude Code, 2026-07-27. Validation environment: remote Codespace, Python 3.11.15, no EnergyPlus._
