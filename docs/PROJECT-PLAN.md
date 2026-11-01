# Project plan: HD 650 playback first, XLR capture later

## Documentation language

All documentation committed to this repository and published to the remote must
be in English, including plans, investigation notes, and test reports from either
OS. Keep private notes and raw captures in the Git-ignored `local/` directory.

## Hardware and goal

Confirmed by the owner on 2026-11-01:

- Creative Sound Blaster AE-9 with its external Audio Control Module (ACM).
- Sennheiser HD 650 headphones connected to the ACM by a jack cable.
- FIFINE K669D microphone connected to the ACM by XLR; 48 V phantom power is not used.
- The card and microphone work together under Windows 11.
- Fedora 44: loading stock `snd_hda_intel` with the AE-9 installed causes a hard lock.
- Priority P0: ordinary stereo playback through the ACM into the HD 650, at 48 kHz,
  with SBX disabled.
- Currently out of scope: XLR capture, CrystalVoice, gain switching, other sample
  rates, bit-perfect playback, rear line-out, S/PDIF, and suspend/resume.

The amplifier still has a physical IEM/Normal/High setting even if the owner does
not adjust it. Do not switch it speculatively or infer a particular gain from the
absence of software control. Start initial playback quietly and do not wear the
headphones until the output level has been checked.

## Current status

| Task | Status |
| --- | --- |
| Clone of upstream `cbfef7e` in Personal/sb-ae9 | Complete |
| Initial build of both modules for Fedora 7.2.13 | Passed |
| Comparison of 103 HDA core exported symbols/CRCs against the kernel | No differences |
| Kernel-level capture restriction for both AE-9 codecs | Implemented locally |
| Host-only PCM builder regression tests | Passed |
| Codec build after the change | Passed |
| GitHub fork | Created: [arkhodakov/sb-ae9](https://github.com/arkhodakov/sb-ae9) |
| Base DSP firmware (`alsa-firmware`) | Package installed; loading by the card not tested |
| Output overlay from the Windows driver | Not obtained |
| Core patch review against current Fedora kernel sources | Not complete |
| Safe Fedora installation/rollback procedure | Still needs preparation |
| Installation and hardware testing | NOT performed |

The presence of `.ko` files does not mean they are installed or loaded. The capture
restriction exists in the new code only; it is not an installed system safeguard.
The boot blacklist remains unchanged.

## Local safety change

In `driver/ca0132/ca0132.c`:

- `ca0132_playback_only()` detects `QUIRK_AE9` and both codec subsystem IDs:
  `0x11020071` and `0x11020072`.
- `ca0132_build_pcms()` and `dbpro_build_pcms()` do not register capture substreams
  or capture-only PCMs on the AE-9. Existing playback streams are preserved.
- Analog capture, What U Hear, secondary analog capture, and digital capture
  are unavailable.
- Other CA0132 cards, including the ordinary ZxR DBPro, retain capture support.
- Init/DSP/MMIO and mixer code are unchanged. This does not fix probe hangs or
  fully isolate the hardware input path; raw hwdep/diagnostic access is not made
  safe either. Do not run hardware poke tools.
- No unsafe bypass module parameter has been added.

The WirePlumber no-capture rules remain as an additional precaution.
The existing session defaults script can fall back to an output-only analog profile.

Checks that do not access the hardware:

```sh
python3 tools/test_ae9_playback_only.py
make -C driver/ca0132 KDIR=/lib/modules/7.2.13-200.fc44.x86_64/build -j4
git --no-pager diff --check
```

The tests compile the actual PCM builders with host stubs. They cover both codecs,
preservation of playback, other quirks, digital input/output combinations, ENOMEM,
and configurations with and without CONFIG_PCI. They do not test real HDA runtime
or DMA behavior.

## P0: preparing the first playback test on Fedora

### 1. Obtain dependencies and firmware while keeping the blacklist

Installed packages: `dkms` 3.4.4, `alsa-firmware` 1.2.4, `gh` 2.103.3, and
`innoextract` 1.9 (verified through RPM before publishing the changes).
Installing these packages does not replace preparation for a safe boot test.

Either of these sources is sufficient for extracting the DSP output overlay:

- `AECMDMasterInstaller_3.4.92.00.exe` from Creative's official website;
- `CtxHda.sys` from the working Windows 11 installation. The extractor checks for
  a known segment and refuses mismatches; do not disable that check.

Use the Creative link in the upstream README. Sound Blaster Command does not need
to be installed or executed on Linux. Its driver binary is needed as a firmware
source, not as a user-facing application.

Store downloaded binaries in the repository's Git-ignored `local/` directory, not
in `docs/`. First run the extractor without sudo, with `--out` pointing into
`local/` and an explicit `--sys` or `--exe` source. Select the source path after
the file is available. Do not commit firmware or Windows binaries to GitHub.

### 2. Prepare a test boot and recovery procedure

Before removing the blacklist:

- review the patch and shared HDA core behavior against the current Fedora kernel;
- ensure firmware, built patched core/codec modules, and no-capture rules are ready;
- verify module installation and resolution through depmod/modinfo, and check that
  the initramfs will not load the stock core before the patched one;
- prepare a separate test boot while retaining a working boot with the blacklist;
- use dracut if necessary, but do not overwrite the only working initramfs without
  a recovery procedure;
- document how to return to the protected boot without activating the AE-9.

`module_blacklist=` is enforced by the kernel. It is not an ordinary modprobe
blacklist that an explicit modprobe can bypass. The next boot's loading order
matters. Do not attempt to hot-unload a shared HDA core that is already in use.

The upstream `uninstall.sh` is not a safe rollback procedure for this machine:
restoring the stock HDA stack without a blacklist may bring back the hard lock.
Do not automatically apply the AMD `iommu=pt` recommendation to this Intel system.

### 3. Initial hardware test criteria

Only after the preceding steps are complete and the owner confirms readiness:

1. No startup hard lock; loading of the intended patched modules is confirmed.
2. The kernel log shows successful DSP overlay loading and ACM bring-up.
3. `/proc/asound/pcm` contains AE-9 playback but no AE-9 capture.
4. PipeWire offers an analog output-only profile.
5. Headphone is selected, OutFX is off, and Master is low; do not change the gain switch.
6. Test brief, quiet playback first, followed by left/right channels, mute, and volume.
7. Test sustained playback and a subsequent cold boot without errors.

Do not test the capture restriction by running `arecord`: checking PCM registration
is sufficient at this stage. Do not use `tools/acm-tool` alongside the ACM worker.
After a crash or Windows session, a warm reboot may not reset the card; upstream
reports that a full power drain can be necessary. Do not cut power while the OS is
running: shut down normally first whenever possible.

## Windows: what is needed now and later

**Now:** confirm the exact Creative driver version and obtain a copy of `CtxHda.sys`
for the extractor if needed. There is no need to set up VM/VFIO or run a tracer for
the first playback test.

**After P0 succeeds:** investigate XLR capture. First record a baseline of successful
K669D recording without 48 V, effects, or monitoring. Then plan traces of init,
start/stop, input selection, and gain/mute. Keep phantom power outside this project
stage unless a new goal explicitly requires it.

Windows Fast Startup/hibernation can leave NTFS unsuitable for writes. Do not use
a shared Git working tree on a hibernated Windows volume from Linux. Use a separate
clone on each OS and synchronize through GitHub.

## GitHub workflow across both operating systems

Fork: https://github.com/arkhodakov/sb-ae9.

- `origin`: `git@github.com:arkhodakov/sb-ae9.git`;
  `upstream`: `https://github.com/verzic/sb-ae9.git`.
- Use separate clones on Fedora and Windows. Do not copy `.git` between OSes.
- Before working, check for a clean working tree, then use `git pull --ff-only`.
- After each stage, review the diff and check for secrets/binaries, then commit
  source changes/documentation and push. Do not use force push for synchronization.
- Label results accurately: build-tested, host-tested, or hardware-tested.
  Do not automatically apply upstream hardware claims to this system.

The remotes are configured on Fedora, and the owner has authenticated GitHub CLI.
Windows needs its own clone and authentication setup. Do not send tokens through
chat or store them in the project.

### Test report template for either OS

For each hardware experiment, create a separate English Markdown report in `docs/`
after reviewing the contents and removing private information:

```text
Date, OS, kernel/Creative driver version:
Source commit and changes used:
Cold boot / warm boot / previous OS:
ACM and connected devices:
Playback profile, sample rate, volume, effects, physical gain setting:
What changed (one change per experiment):
Expected and actual results:
Sanitized diagnostic excerpts:
How the test ended and the safe configuration was restored:
Next step:
```

Do not publish local usernames/hostnames, disk UUIDs, tokens, private audio content,
Creative binaries, or raw memory dumps. Keep raw logs/captures in `local/` and
transfer them between OSes separately if needed.
