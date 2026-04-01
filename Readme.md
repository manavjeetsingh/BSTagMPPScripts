# README

## Microcontroller script

Flash `TagMicrocontrollerCode/usbAPI.ip` on esp32 microcontroller using arduinio IDE.

## 2. Setting up the Python environment

Create and activate a virtual environment, then install dependencies:

```bash
# Create virtual environment
python -m venv .venv

# Activate (macOS/Linux)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Installing ribbn library
cd ribbn_scripts
pip install -e .
cd ..
```

Tested with python 3.12.

## Running phase measurement script.

Run `measurePhasesMultiThreaded.py` with the required arguments:

```bash
# Basic usage with RFGen exciter (type 0, default)
python measurePhasesMultiThreaded.py --tag1-com COM2 --tag2-com COM3 --exc-power 13

# Using BladeRF exciter (type 1)
python measurePhasesMultiThreaded.py --tag1-com COM2 --tag2-com COM3 --exc-power 10 --exc-type 1

# Custom tag names and Linux serial ports
python measurePhasesMultiThreaded.py --tag1-com /dev/ttyUSB0 --tag2-com /dev/ttyUSB1 --exc-power 13 --tag1-name TagA --tag2-name TagB

# All arguments
python measurePhasesMultiThreaded.py --tag1-com COM2 --tag2-com COM3 --exc-power 13 --exc-type 0 --tag1-name TagV32_9 --tag2-name TagV32_8 --csv-path ./results.csv --freq-start 900 --freq-stop 950 --freq-step 5 --config "Old Code/config.cal"

# Show full help
python measurePhasesMultiThreaded.py --help
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--tag1-com` | yes | — | COM port for tag 1 (e.g. `COM2` or `/dev/ttyUSB0`) |
| `--tag2-com` | yes | — | COM port for tag 2 (e.g. `COM3` or `/dev/ttyUSB1`) |
| `--exc-power` | yes | — | Exciter power/gain in dBm (e.g. `13`) |
| `--exc-type` | no | `0` | Exciter type: `0`=RFGen, `1`=BladeRF |
| `--tag1-name` | no | `TagV32_9` | Label for tag 1 |
| `--tag2-name` | no | `TagV32_8` | Label for tag 2 |
| `--csv-path` | no | `./test.csv` | Path to save/append CSV results |
| `--freq-start` | no | `915` | Frequency sweep start in MHz |
| `--freq-stop` | no | `935` | Frequency sweep stop in MHz (inclusive) |
| `--freq-step` | no | `10` | Frequency sweep step size in MHz |
| `--config` | no | `Old Code/config.cal` | Path to calibration `.cal` file |