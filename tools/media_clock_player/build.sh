#!/bin/sh
# Build the host media-clock player next to its source (no install, no download).
set -eu
cd "$(dirname "$0")"
xcrun swiftc -O -o media_clock_player main.swift
shasum -a 256 main.swift media_clock_player
