# Search Definition API

We provide a uniform “search symbol by type” API that finds **definitions** for symbols in 

1. Built-ins (e.g., `print`, `int`)

2. Stdlib modules/members (e.g., `collections`, `os.path.join`)

3. Third-party modules/members (e.g., `numpy`, `numpy.average`)

4. Workspace symbols (user-defined symbols in the codebase)

Types of symbol includes

- Module

- Class

- Method

- Property

- Field

- Function

- Variable

- Constant

The return value is a list of definition info, as is defined in later section.

## Design Overview

We have different way to search for different types of symbol:

### Workspace symbols

This refers to any symbol that is not built-in, from standard library or third-party library. Pretty much anything defined by users.

We use LSP `workspace/symbol`. Per LSP, the query is free-form. In specific, we will use `jedi-language-server`, which allows us to use more versatile queries:

- query with path like `mylib.utils.FoobarHelper`, that only search for `FoobarHelper` symbol in file `mylib/utils.py`

- prefix query like `Foobar` that can matches to `Foobar`, `FoobarHelper`, etc.

We provide the following api for this type of search

```python
def search_ws_symbol_def(query: str) -> List[dict]:
    pass 

## Examples:
search_ws_symbol_def("main")
search_ws_symbol_def("core.math_utils.Calculator")
```

### Non-workspace symbols: built-ins / standard library / third-party library

`workspace/symbol` doesn't apply to symbols in built-ins, standard library, or third-party libraires.

As an alternative, we have a general method to search for a specific symbol in a specific library: given library name `<library>` and symbol name `<symbol>`, we create a scratch file `_scratch_<unique id>.py` of the form

```python
import <library> as __m
__m.<symbol>
```

and call `textDocument/definition` at line 1, character `len(f"__m.{symbol}") - 1`, file `_scratch_<unique id>.py`. j

Note that 

- `<library>` can be a submodule, such as `os.path`.

- `<symbol>` can be something like `<class_name>.<method_name>` when searching for method.

> Note: A more natural design like the one below won't work, because we may want to search for the method of a class from a library
> 
> ```python
> from <library> import <symbol>
> <symbol>
> ```
> 
> and search for line 1 character 0 in file `scratch-<random id>.py`.
> 
> A counter-example would be `pathlib.Path.cwd`:
> 
> - if we set `<library>
> 
> ```python
> from pathlib import Path.cwd
> ```
> 

Below are some concrete examples for each type of search

For built-ins, we have scratch file

```python
import builtins
builtins.int
```

For standard library, we have scratch file

```python
import os.path
os.path.join
```

For third-party library, we have scratch file

```python
import numpy
numpy.average
```

We provide a unified api that search symbol in library as follows

```python
def search_non_ws_symbol_def(library: str, symbol: str | None) -> List[dict]
```

This can be used to implement two more user-friendly apis:

Search in standard library and third-party library

```python
def search_non_workspace_library_symbol(library: str, symbol: str | None) -> List[dict]:
    return search_non_ws_symbol_def(library, symbol)

## Examples: 
# search def for the function `os.path.join`
search_non_workspace_library_symbol("os.path", "join")
# search def for the class `numpy.ndarray`
search_non_workspace_library_symbol("numpy", "ndarray")
# search def for the library `click` itself
search_non_workspace_library_symbol("click")
```

Search in built-ins

```python
def search_builtins_symbol_def(symbol: str | None) -> List[dict]:
    return search_non_ws_symbol_def("builtins", symbol)
```

Note that, unlike `workspace/symbol` which returns both location and type of symbol, `textDocument/definiton` only return the location. Thus, we need to call `textDocument/documentSymbol` (or `request_document_symbol` in multilspy) on the location returned by `textDocument/definition` to get the symbol type.

#### Special Case: Search for library definition

Optionally, we can pass in a `None` symbol, which allows us to search for only lirbary definition. The scratch file will become

```python
import <library>
```

and we will call `textDocument/definiton` on line 0 character 7 in file `scratch-<unique id>.py`.

The search result can be used as input to [search reference api](./search_ref.md), which search refernece to a symbol (workspace or non-workspace) given (file, line, character).

### Return value of search definition

A list of symbol definition info. Each symbol definition info consists of 

- uri to the file containing the symbol definition

- symbol start location, defined triple of `(file_rel_path, line_no, character_no)`. This can be used to search for symbol references within workspace. `file_rel_path` is the path to file relative to workspace root. `line_no` and `characgter_no` are 0-based index.

- Symbol type, as is defined in the [LSP protocol](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#textDocument_documentSymbol).

The list is de-duplicated by `(uri, start_loc)`

## Notes

- When finding def of a workspace method via query, you must specify both class and method, such as `Calculator.add`. Otherwise it won't work.