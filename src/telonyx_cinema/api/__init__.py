"""FastAPI package."""

# Патч намеренно подключается через import hook:
# исходный publishing.py уже содержит рабочий роутер, а здесь мы безопасно
# переопределяем только логику поиска/фильтрации картинок после импорта модуля.
import importlib
import importlib.abc
import importlib.machinery
import sys


class _PublishingPatchLoader(importlib.abc.Loader):
    def __init__(self, loader):
        self.loader = loader

    def create_module(self, spec):
        if hasattr(self.loader, "create_module"):
            return self.loader.create_module(spec)
        return None

    def exec_module(self, module):
        self.loader.exec_module(module)
        from . import publishing_patch
        publishing_patch.apply(module)


class _PublishingPatchFinder(importlib.abc.MetaPathFinder):
    TARGET = __name__ + ".publishing"

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.TARGET:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            spec = finder.find_spec(fullname, path, target) if hasattr(finder, "find_spec") else None
            if spec and spec.loader:
                spec.loader = _PublishingPatchLoader(spec.loader)
                return spec
        return None


if not any(isinstance(finder, _PublishingPatchFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _PublishingPatchFinder())
