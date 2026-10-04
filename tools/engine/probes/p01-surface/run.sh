#!/bin/sh
cd "$(dirname "$0")"
echo "### node_modules/.bin (all binaries from the shex install)"
ls /w/node_modules/.bin | grep -E '^(shex|json-to|dctap)' | sed 's/^/  /'
echo "### programmatic API"
node run.js
