# Conformance fixtures

`plans/*.gtnh` and `solver.test.ts.snap` are copied unchanged from
[ShadowTheAge/gtnh](https://github.com/ShadowTheAge/gtnh) at commit
`af8c79888ec859913b27543c1381c3c11c24658f`: its `tests/` folder (the calculator's own test plans)
and its Jest snapshot `src/tests/__snapshots__/solver.test.ts.snap`, which records, for every
recipe row of every plan, what the app computes (runs per minute, machine count, power and
overclock factors, overclock label) against the 2.9 `data.bin`.

`tests/test_conformance.py` solves each plan with this package and compares the results with the
snapshot. It needs the real `data.bin`, which is never committed (it has no license): set
`GTNH_SHADOW_DATA` to it, or let CI's conformance job fetch it.

These files are under the MIT License:

    Copyright (c) 2025 ShadowTheAge

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
