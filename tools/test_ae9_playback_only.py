#!/usr/bin/env python3
"""Host-only PCM regression tests; no kernel modules or audio devices are used.

Compile the actual PCM templates, builders, quirk macros and AE-9 detector from
ca0132.c. The stub allocator models zero-initialized HDA PCM descriptors and can
fail each allocation. Callback bodies are inert: their identities are checked,
not their hardware behavior. Run: python3 tools/test_ae9_playback_only.py
"""

import errno
import itertools
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "driver/ca0132/ca0132.c"
CALLBACKS = (
    "ca0132_playback_pcm_prepare",
    "ca0132_playback_pcm_cleanup",
    "ca0132_playback_pcm_delay",
    "ca0132_capture_pcm_prepare",
    "ca0132_capture_pcm_cleanup",
    "ca0132_capture_pcm_delay",
    "ca0132_dig_playback_pcm_open",
    "ca0132_dig_playback_pcm_close",
    "ca0132_dig_playback_pcm_prepare",
    "ca0132_dig_playback_pcm_cleanup",
)

STUB = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define HDA_FIXUP_ID_NOT_SET (-1)
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
#define HDA_PCM_TYPE_SPDIF 1

/* Only fields consumed by the extracted code; callbacks are never invoked. */
typedef void (*callback)(void);
struct hda_pcm_ops {
    callback open, close, prepare, cleanup, get_delay;
};
struct hda_pcm_stream {
    unsigned int substreams, channels_min, channels_max;
    unsigned short nid;
    const void *chmap;
    struct hda_pcm_ops ops;
};
struct hda_pcm {
    const char *name;
    struct hda_pcm_stream stream[2];
    unsigned int pcm_type;
    bool own_chmap;
};
struct hda_codec {
    struct { unsigned int subsystem_id; } core;
    void *spec;
    int fixup_id;
};
struct ca0132_spec {
    struct hda_codec *codec;
    bool use_alt_functions;
    unsigned short dacs[1], adcs[3], dig_out, dig_in;
    struct { int max_channels; } multiout;
};
static const int ca0132_alt_chmaps[] = { 0 };
static struct hda_pcm pcms[8];
static unsigned int pcm_count, attempts, fail_at;

static struct hda_pcm *snd_hda_codec_pcm_new(struct hda_codec *codec,
                                           const char *name)
{
    (void)codec;
    if (++attempts == fail_at)
        return NULL;
    assert(pcm_count < sizeof(pcms) / sizeof(pcms[0]));
    struct hda_pcm *pcm = &pcms[pcm_count++];
    memset(pcm, 0, sizeof(*pcm));
    pcm->name = name;
    return pcm;
}
"""

MAIN = r"""
static void print_stream(const struct hda_pcm_stream *s)
{
    printf("[%u,%u,%u,%u,%u,%u,%u,%u,%u,%u]",
           s->substreams, s->channels_min, s->channels_max, s->nid,
           callback_id(s->ops.prepare), callback_id(s->ops.cleanup),
           callback_id(s->ops.get_delay), callback_id(s->ops.open),
           callback_id(s->ops.close), s->chmap != NULL);
}

int main(int argc, char **argv)
{
    assert(argc == 8);
    struct hda_codec codec = { 0 };
    struct ca0132_spec spec = {
        .codec = &codec, .dacs = { 2 }, .adcs = { 7, 8, 10 },
    };
    codec.spec = &spec;
    unsigned int q;
    for (q = 0; q < sizeof(quirks) / sizeof(quirks[0]); ++q)
        if (!strcmp(argv[1], quirks[q].name))
            break;
    assert(q < sizeof(quirks) / sizeof(quirks[0]));
    codec.fixup_id = quirks[q].value;
    codec.core.subsystem_id = strtoul(argv[2], NULL, 0);
    spec.use_alt_functions = atoi(argv[3]);
    unsigned int digital = strtoul(argv[4], NULL, 0);
    spec.dig_out = (digital & 1) ? 5 : 0;
    spec.dig_in = (digital & 2) ? 9 : 0;
    spec.multiout.max_channels = atoi(argv[5]);
    fail_at = strtoul(argv[6], NULL, 0);
    if (atoi(argv[7]) && ca0132_quirk(&spec) == QUIRK_AE9)
        ae9_detect_quirk(&codec);
    int result = ca0132_codec_build_pcms(&codec);
    printf("{\"result\":%d,\"attempts\":%u,\"pcms\":[", result, attempts);
    for (unsigned int i = 0; i < pcm_count; ++i) {
        const struct hda_pcm *p = &pcms[i];
        printf("%s[\"%s\",%u,%u,", i ? "," : "", p->name,
               p->pcm_type, p->own_chmap);
        print_stream(&p->stream[SNDRV_PCM_STREAM_PLAYBACK]);
        putchar(',');
        print_stream(&p->stream[SNDRV_PCM_STREAM_CAPTURE]);
        putchar(']');
    }
    puts("]}");
    return 0;
}
"""


def function(source, name):
    """Extract a top-level function, including its unmodified body."""
    start = re.search(r"^static (?:int|void) " + name + r"\(", source, re.M)
    if start is None:
        raise AssertionError(f"Missing real function: {name}")
    end = source.index("\n}", start.start()) + len("\n}")
    return source[start.start():end]


def harness(source):
    enum_start = source.index("enum {\n\tQUIRK_ALIENWARE,")
    enum_end = source.index("\n};", enum_start) + len("\n};")
    quirk_enum = source[enum_start:enum_end]
    quirks = re.findall(r"\bQUIRK_\w+\b", quirk_enum)
    macro_start = source.index("#ifdef CONFIG_PCI\n#define ca0132_quirk")
    macro_end = source.index("#endif", macro_start) + len("#endif")
    pcm_start = source.index("static const struct hda_pcm_stream ca0132_pcm_analog_playback")
    pcm_end = source.index("static void init_output", pcm_start)
    callbacks = "\n".join(f"static void {name}(void) {{}}" for name in CALLBACKS)
    callback_ids = "\n".join(
        f"    if (cb == {name}) return {index};"
        for index, name in enumerate(CALLBACKS, 1)
    )
    table = ",\n".join(f'{{ "{name}", {name} }}' for name in quirks)
    return "\n".join((
        STUB, quirk_enum, source[macro_start:macro_end], callbacks,
        "static unsigned int callback_id(callback cb) {\n"
        "    if (!cb) return 0;\n" + callback_ids + "\n    abort();\n}",
        "static const struct { const char *name; int value; } quirks[] = {\n"
        + table + "\n};",
        source[pcm_start:pcm_end],
        function(source, "ae9_detect_quirk"),
        function(source, "ca0132_codec_build_pcms"), MAIN,
    ))


def stream(kind=None, nid=0, channels=2):
    # substreams, min/max channels, NID, prepare/cleanup/delay/open/close, chmap
    if kind is None:
        return [0] * 10
    ops = {
        "analog_playback": [1, 2, 3, 0, 0],
        "analog_capture": [4, 5, 6, 0, 0],
        "digital_playback": [9, 10, 0, 7, 8],
        "digital_capture": [0, 0, 0, 0, 0],
    }
    return [1, 2, channels, nid, *ops[kind], 0]


def expected_pcms(quirk, subsystem, alt, digital, channels, detect, pci=True):
    if not pci:
        quirk, alt = "QUIRK_NONE", False
    if detect and quirk == "QUIRK_AE9" and subsystem == 0x11020072:
        quirk = "QUIRK_ZXR_DBPRO"
    capture = quirk != "QUIRK_AE9" and subsystem not in (0x11020071, 0x11020072)
    pcms = []
    if quirk == "QUIRK_ZXR_DBPRO":
        if capture:
            pcms.append(["CA0132 Alt Analog", 0, 0, stream(), stream("analog_capture", 7)])
    else:
        pcms.append([
            "CA0132 Analog", 0, int(alt), stream("analog_playback", 2, channels),
            stream("analog_capture", 7) if capture else stream(),
        ])
        if capture:
            if not alt:
                pcms.append(["CA0132 Analog Mic-In2", 0, 0, stream(), stream("analog_capture", 8)])
            pcms.append(["CA0132 What U Hear", 0, 0, stream(), stream("analog_capture", 10)])
    if digital & 1 or (capture and digital & 2):
        pcms.append([
            "CA0132 Digital", 1, 0,
            stream("digital_playback", 5) if digital & 1 else stream(),
            stream("digital_capture", 9) if capture and digital & 2 else stream(),
        ])
    return pcms


class PlaybackOnlyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="ae9-pcm-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        source = directory / "pcm_test.c"
        source.write_text(harness(SOURCE.read_text()))
        cls.binaries = {}
        for pci in (True, False):
            binary = directory / ("pcm-pci" if pci else "pcm-no-pci")
            command = shlex.split(os.environ.get("CC", "cc")) + [
                "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O0",
            ]
            if pci:
                command.append("-DCONFIG_PCI")
            subprocess.run(command + [str(source), "-o", str(binary)], check=True, timeout=30)
            cls.binaries[pci] = binary

    def check_case(self, quirk, subsystem, alt, digital, channels=6,
                   detect=False, pci=True, failures=False):
        expected = expected_pcms(quirk, subsystem, alt, digital, channels, detect, pci)
        # Also fail just beyond the last allocation (including the zero-PCM case).
        fail_points = range(len(expected) + 2) if failures else (0,)
        for fail_at in fail_points:
            with self.subTest(quirk=quirk, subsystem=hex(subsystem), alt=alt,
                              digital=digital, channels=channels, fail_at=fail_at,
                              detect=detect, pci=pci):
                result = subprocess.run([
                    str(self.binaries[pci]), quirk, hex(subsystem), str(int(alt)),
                    str(digital), str(channels), str(fail_at), str(int(detect)),
                ], check=True, capture_output=True, text=True, timeout=5)
                actual = json.loads(result.stdout)
                failed = 0 < fail_at <= len(expected)
                self.assertEqual(actual, {
                    "result": -errno.ENOMEM if failed else 0,
                    "attempts": fail_at if failed else len(expected),
                    "pcms": expected[:fail_at - 1] if failed else expected,
                })

    def test_ae9_both_codecs_and_quirk_overrides(self):
        identities = (
            ("QUIRK_AE9", 0x11020071, True),
            ("QUIRK_AE9", 0x11020072, True),
            ("QUIRK_ZXR_DBPRO", 0x11020072, False),
            ("QUIRK_AE9", 0, False),
            ("QUIRK_NONE", 0x11020071, False),
            ("QUIRK_NONE", 0x11020072, False),
            ("QUIRK_ZXR_DBPRO", 0x11020071, False),
        )
        for (quirk, subsystem, detect), alt, digital, channels in itertools.product(
                identities, (False, True), range(4), (2, 6)):
            self.check_case(quirk, subsystem, alt, digital, channels, detect, failures=True)

    def test_other_cards_keep_capture_and_playback(self):
        identities = (
            ("QUIRK_NONE", 0),
            ("QUIRK_ALIENWARE", 0x10280685),
            ("QUIRK_ALIENWARE_M17XR4", 0x1028057B),
            ("QUIRK_SBZ", 0x11020023),
            ("QUIRK_ZXR", 0x11020033),
            ("QUIRK_ZXR_DBPRO", 0x1102003F),
            ("QUIRK_ZXR_DBPRO", 0x12340072),
            ("QUIRK_R3DI", 0x1458A016),
            ("QUIRK_R3D", 0x11020013),
            ("QUIRK_AE5", 0x11020051),
            ("QUIRK_AE7", 0x11020081),
        )
        for (quirk, subsystem), alt, digital, channels in itertools.product(
                identities, (False, True), range(4), (2, 6)):
            self.check_case(quirk, subsystem, alt, digital, channels, failures=True)

    def test_subsystem_guard_without_config_pci(self):
        for subsystem, alt, digital in itertools.product(
                (0x11020071, 0x11020072, 0x1102003F), (False, True), range(4)):
            self.check_case("QUIRK_AE9", subsystem, alt, digital, pci=False, failures=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
