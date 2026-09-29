#!/bin/sh
cd "$(dirname "$0")"
# depends on p03-iteration having produced outA.val
[ -f ../p03-iteration/outA.val ] || sh ../p03-iteration/run.sh > /dev/null 2>&1
node run.js
