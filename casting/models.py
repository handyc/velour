from django.db import models


class Experiment(models.Model):
    """One row per experiment in the Casting library.

    Each experiment has a canonical C source (served from
    static/casting/sources/) and an optional live JS port
    (static/casting/js/<js_module_name>.js) that exposes a
    `window.Casting_<js_module_name>.run()` function returning a
    formatted text block.
    """

    STATUS_PENDING = 'pending'
    STATUS_SUCCESS = 'success'
    STATUS_FAIL    = 'fail'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'pending (yellow)'),
        (STATUS_SUCCESS, 'success (green)'),
        (STATUS_FAIL,    'fail (red)'),
    ]

    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=120)
    tagline = models.CharField(max_length=200, blank=True)
    body_md = models.TextField(blank=True)

    weight_bits = models.PositiveIntegerField(
        help_text="Number of bits in a single model's weight bitstring."
    )
    target_family = models.CharField(max_length=120)
    search_method = models.CharField(max_length=80)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING,
        help_text="Verdict after running: green (works), yellow (untested), red (fails)."
    )

    c_source_filename = models.CharField(
        max_length=80,
        help_text="Filename under static/casting/sources/ (e.g. byte_model.c).",
    )
    js_module_name = models.CharField(
        max_length=80, blank=True,
        help_text="Basename under static/casting/js/ without .js, or blank if C-only.",
    )

    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'id']

    def __str__(self):
        return self.title

    @property
    def search_space(self) -> int:
        return 1 << self.weight_bits

    @property
    def search_space_display(self) -> str:
        n = self.search_space
        if n < 1_000_000:
            return f"{n:,}"
        return f"2^{self.weight_bits}"
