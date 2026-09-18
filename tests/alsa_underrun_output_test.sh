#!/bin/sh

set -eu

stderr_file=$(mktemp "${TMPDIR:-/tmp}/exult-alsa-underrun-stderr.XXXXXX")
stdout_file=$(mktemp "${TMPDIR:-/tmp}/exult-alsa-underrun-stdout.XXXXXX")
trap 'rm -f "$stderr_file" "$stdout_file"' EXIT HUP INT TERM

set +e
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=alsa timeout --signal=KILL 3s ./exult --bg --nomenu \
	>"$stdout_file" 2>"$stderr_file"
status=$?
set -e

case "$status" in
	0|124|137|143)
		;;
	*)
		cat "$stdout_file" >&2
		cat "$stderr_file" >&2
		exit "$status"
		;;
esac

if ! grep -Fq "Creating AudioMixer..." "$stdout_file" \
		|| ! grep -Fq "Audio opened using format:" "$stdout_file"; then
	cat "$stdout_file" >&2
	cat "$stderr_file" >&2
	exit 1
fi

if grep -Fq "ALSA lib pcm.c:8740:(snd_pcm_recover) underrun occurred" "$stderr_file"; then
	cat "$stderr_file" >&2
	exit 1
fi
