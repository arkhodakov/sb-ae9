# AE-9: Fedora Review and XLR Investigation Plan

Date: 2026-11-01. Upstream commit reviewed: `cbfef7e0de0b90915793715d13ba5b6c79cd5ea9`.

This is the initial upstream review, predating local modifications. Subsequent
changes and the updated configuration are described in [PROJECT-PLAN.md](PROJECT-PLAN.md):
capture PCM registration for both AE-9 codecs has already been disabled in the
local code; the modules remain uninstalled and have not been tested on hardware.

## Review Scope

The work consisted of reading system information, analyzing source code, and
building locally. The installer, hardware diagnostic utilities, module
loading/unloading, and changes to firmware, boot parameters, or audio settings
were NOT performed. The user confirmed a reproducible complete system freeze
when loading `snd_hda_intel` with the AE-9 connected. The existing blacklist
is being preserved.

The previous shared ChatGPT conversation could not be retrieved as text;
its conclusions are not included in this analysis.

## Observed System

- Fedora Workstation 44, kernel `7.2.13-200.fc44.x86_64`.
- Intel platform; AE-9: `04:00.0`, PCI `1102:0010`, subsystem `1102:0071`.
- The PCI tree includes an ASMedia ASM1083/1085 bridge.
- No driver is bound to the AE-9. Only the C922 Webcam is registered in ALSA;
  PipeWire uses Dummy Output and the webcam microphone.
- Boot parameter: `module_blacklist=snd_hda_intel,snd_hda_code_c_ca0132`.
  The second name contains a typo relative to `snd_hda_codec_ca0132`;
  `snd_hda_intel` is indeed blocked, as confirmed by the log.
  This is an observation, not a recommendation to remove or change the protection now.
- Secure Boot is disabled.
- Matching `kernel-devel`, GCC, make, and akmods are installed.
- DKMS and `alsa-firmware` are not installed. No files were found at
  `/usr/lib/firmware/ctefx*` or `/usr/lib/firmware/ae9*`.
- PipeWire 1.6.11, WirePlumber 0.5.18.

An XLR microphone is an analog device: its model cannot be identified through
PCI/USB enumeration. The presence and state of the ACM were not queried through
hardware access.

## Build Verification

The following commands were successfully run from the project root:

```sh
make -C driver/hda-core KDIR=/lib/modules/7.2.13-200.fc44.x86_64/build -j4
make -C driver/ca0132 KDIR=/lib/modules/7.2.13-200.fc44.x86_64/build -j4
```

The resulting modules were `driver/hda-core/snd-hda-core.ko` and
`driver/ca0132/snd-hda-codec-ca0132.ko`. No source files were changed.

Warnings: GCC has a different RPM build from the one used for the kernel
(16.2.1-3 instead of 16.2.1-2); BTF generation was skipped because vmlinux was
unavailable. There were no build errors.

Additionally, `driver/hda-core/Module.symvers` was compared with the
`snd-hda-core` entries in `/usr/src/kernels/7.2.13-200.fc44.x86_64/Module.symvers`:
103 exported symbols in each, with no missing or extra symbols and no CRC
differences. This does not test runtime behavior or guarantee that all internal
assumptions of the HDA core ported from Linux 7.0 are compatible with kernel 7.2.

## Reusable Components

- The AE-9 implementation in `driver/ca0132/ca0132.c`: DSP bring-up,
  DAC/output routing, the ACM UART protocol, volume adjustment, and buttons.
- `patches/0001-ALSA-hda-flush-posted-writes-in-azx_int_clear.patch`:
  readback after groups of posted MMIO writes in the HDA controller/stream code.
  The freeze scenario described by the author resembles this machine's problem,
  but neither the causal connection nor the fix has been verified on this machine.
- The DKMS configuration and WirePlumber 0.5 rules.
- Reverse-engineering notes and Windows initialization/playback traces in `docs/`.
- DSP output overlay extraction from Creative's proprietary Windows driver.
  Binary firmware is not included in the repository.

The project is GPL-2.0; custom driver changes can be developed on this basis
in compliance with the license. Rights to Creative firmware must be considered
separately.

## Why XLR Requires More Than Fedora Adaptation

The README explicitly lists capture/XLR/48 V as unsupported and reports a hard
lock when opening capture. Building for Fedora does not fix this.

### Capture Protection Exists Only at the Session Level

`install/52-ae9-no-capture.conf` and `.lua` disable matching WirePlumber input
nodes. `install.sh` places them in a single user's configuration.
This does not protect direct ALSA access or other sessions.

In `ca0132_build_pcms()`, capture PCMs are still registered;
`ca0132_capture_pcm_prepare()` calls `snd_hda_codec_setup_stream()`
without an AE-9-specific block. Before future playback tests, separate
kernel-level protection against unsupported capture is needed, accounting for
both codecs and the available PCMs. It will not replace a fix for the probe hang.

### A Foundation Exists, but No End-to-End Input Route Has Been Confirmed

For the AE-9, the code includes ADC NID `0x07`, MIC1/MIC2 connection point
settings, DSP capture volume, and generic Capture/Mic Boost controls. This does
not prove that they correspond to the ACM's physical XLR input or provide
working recording.

In `ca0132_alt_select_in()`, the AE-9 is grouped with the AE-5, including
`ca0113_mmio_command_set(codec, 0x30, 0x28, ...)` and CHIPIO writes to
`0x18b098/0x18b09c`. However, the AE-9-specific initialization explicitly
explains that the AE-9 has no group-0x30 device and excludes such a command
in its own section. This is a concrete inconsistency to investigate, NOT a
proven cause of the hang. Commands should not be removed mechanically without
establishing the correct path.

`docs/reverse-engineering/ctxhda-acm-analysis.md` describes UART commands for
phantom power and its readback. `ae9_acm_init()` already sends an OFF command,
but there is no complete ALSA 48 V control with state confirmation.
Adding a 48 V switch is not enough to obtain audio.
HDA VREF and XLR 48 V phantom power are different mechanisms.

The physical ADC/codec for XLR, the input mux, preamp control, and the complete
route to HDA capture DMA have not been established. The role of the second codec
in XLR recording also requires verification.

## Work Plan

1. Preserve the blacklist and the working boot configuration. Do not blindly run
   `install.sh`, `uninstall.sh`, hardware poke tools, or ALSA capture.
2. Before installation: check the patch against the current Fedora kernel sources,
   add kernel-level protection against accidental capture, and plan rollback and
   a separate test boot. The HDA core is shared: replacing it affects more than
   just the AE-9.
3. Adapt installation/removal for Fedora: dependencies, firmware,
   depmod/module priority, checking initramfs contents and using dracut if needed,
   and preserving a safe blacklist on failure/removal.
   The current installer already accepts Fedora DKMS `extra/`, but does not
   provide a complete, safe installation/rollback transaction.
   The AMD recommendation `iommu=pt` must not be automatically applied to Intel.
4. Test playback as a separate stage, with an informed acceptance of the risk of
   a freeze. Even successful playback does not justify enabling capture.
5. Obtain Windows traces specifically of successful XLR recording: cold
   initialization, start/stop, input selection, and gain/mute; test phantom power
   only after establishing the microphone model and safe conditions.
   Start without CrystalVoice/monitoring.
6. Record BAR0/stream DMA state, CORB/RIRB for both codecs, BAR2 UART TX/RX,
   command engine/GPIO, timestamps, and an actual test audio recording.
   Raw traces are needed: the existing `ops.py` filters out some information,
   and an earlier investigation noted an error in capturing RIRB responses.
7. Use the traces to implement AE-9 input routing, then basic capture in one
   format, repeated opening/closing, and duplex operation. Effects and additional
   sample rates should follow only after basic recording is stable.

A freeze when loading HDA and a freeze when starting capture are different
failure points. It is not yet possible to promise either that a single patch
will fix both or a timeline for full XLR support.

## Owner's Clarifications

- A FIFINE K669D is connected directly to the ACM via XLR; 48 V is not used.
- Sennheiser HD 650 headphones are connected to the ACM with a jack cable.
- Windows 11 is available, and the microphone and card work together there.
- The first priority is headphone audio, without developing XLR, SBX, or gain control.
- The previous shared conversation remains unavailable.
