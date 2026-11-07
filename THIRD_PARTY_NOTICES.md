# Third-party notices

This project's own code is © 2026 Artemii Storozhevskikh, licensed under
PolyForm Noncommercial 1.0.0 (see [LICENSE](LICENSE)).

The repository contains **no** third-party source code, fonts, icons, templates,
models or datasets. The screenshots in `docs/` were made by the author and show
fictional data.

The libraries below are **not** included in this repository. They are optional
dependencies, downloaded from PyPI by the user's own `pip` when the launcher or
`pip install` runs. Each one remains under its own license, and its copyright
notice is reproduced here.

## Direct dependencies

Listed in `requirements.txt` and `pyproject.toml`.

**certifi** — Mozilla Public License 2.0
- Author: Kenneth Reitz.
- Carries a modified bundle of CA root certificates from Mozilla.
- Used unmodified, as a separate package.
- Source: https://github.com/certifi/python-certifi

**python-docx** — MIT License
- Copyright (c) 2013 Steve Canny, https://github.com/scanny
- Source: https://github.com/python-openxml/python-docx

**python-pptx** — MIT License
- Copyright (c) 2013 Steve Canny, https://github.com/scanny
- Source: https://github.com/scanny/python-pptx

**pypdf** — BSD 3-Clause License
- Copyright (c) 2006-2008, Mathieu Fenniak.
- Some contributions copyright (c) 2007, Ashish Kulkarni.
- Source: https://github.com/py-pdf/pypdf

## Installed along with them

Pulled in by python-docx, python-pptx and pypdf.

**lxml** — BSD 3-Clause License
- Copyright (c) 2004 Infrae. All rights reserved.
- Source: https://github.com/lxml/lxml

**typing_extensions** — Python Software Foundation License 2.0
- Copyright (c) 2001-2023 Python Software Foundation; All Rights Reserved.
- Source: https://github.com/python/typing_extensions

**Pillow** — MIT-CMU License
- Copyright © 1997-2011 by Secret Labs AB.
- Copyright © 1995-2011 by Fredrik Lundh and contributors.
- Source: https://github.com/python-pillow/Pillow

**XlsxWriter** — BSD 2-Clause License
- Copyright (c) 2013-2025, John McNamara.
- Source: https://github.com/jmcnamara/XlsxWriter

## Development tools

Used only in CI and development; not required to run the program.

- **ruff** (linter) — MIT License, Astral Software Inc.
- **actions/checkout**, **actions/setup-python** (GitHub Actions) — MIT License, GitHub, Inc.

## External services

The program talks to these services over their public APIs. Nothing from them
is stored in this repository.

- **newLXP** learning platform (`api.newlxp.ru`).
- **OpenAI** and **Anthropic** APIs, with the user's own key and account.
