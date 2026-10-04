#!/bin/sh
# Probe 7: is there a static analyser (a "shexmap-check") in the shipped build?
cd "$(dirname "$0")"
echo "### binaries matching check/lint/analy in the whole install"
ls /w/node_modules/.bin | grep -iE 'check|lint|analy' || echo "  (none)"
echo
echo "### any source symbol resembling a ShExMap static checker"
grep -rliE 'shexmap-?check|staticCheck|checkMap' /w/node_modules/@shexjs/ 2>/dev/null || echo "  (none)"
echo
echo "### shex-validate --diagnose on a target schema with a variable nothing binds"
/w/node_modules/.bin/shex-validate -x ../p05-lineage/target-typo.shex --diagnose 2>&1 | head -12
echo "   exit=$?"
echo
echo "### what a host-side checker would need: Map codes per schema"
echo "-- source --"; node vars.js ../p03-iteration/source.shex
echo "-- target (typo'd) --"; node vars.js ../p05-lineage/target-typo.shex
