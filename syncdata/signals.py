from django import dispatch

importer_pre_launch = dispatch.Signal(providing_args=['importer'])
importer_pre_launch.__doc__ = """Send before importer launch."""

importer_post_launch = dispatch.Signal(providing_args=['importer'])
importer_post_launch.__doc__ = """Send after importer launch."""
