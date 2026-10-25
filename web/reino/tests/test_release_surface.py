"""Release routes, brand preservation, and historical-panel tenant boundary."""
import uuid
from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from reino.models import MerchantMember
from reino import services_theme
from reino.tests import ReinoTestCase


class ReleaseSurfaceTests(ReinoTestCase):
    def test_all_named_routes_resolve_without_server_errors(self):
        user = User.objects.create_superuser('release-operator', 'qa@example.test', 'test-release')
        MerchantMember.objects.create(user=user, merchant=self.merchant_a, role='owner')
        self.client.force_login(user)
        checked = []
        def visit(patterns):
            for p in patterns:
                if isinstance(p, URLResolver):
                    visit(p.url_patterns)
                elif isinstance(p, URLPattern) and p.name:
                    values = {}
                    for key, converter in p.pattern.converters.items():
                        if key == 'slug': values[key] = self.store_a.slug
                        elif key == 'product_slug': values[key] = self.product.slug
                        elif key == 'producto': values[key] = 'beige-harness'
                        elif converter.__class__.__name__ == 'UUIDConverter': values[key] = uuid.uuid4()
                        elif converter.__class__.__name__ == 'IntConverter': values[key] = 999999
                        else: values[key] = 'missing'
                    url = reverse(p.name, kwargs=values)
                    with self.subTest(route=p.name):
                        response = self.client.get(url)
                        self.assertLess(response.status_code, 500)
                    checked.append(p.name)
        visit(get_resolver().url_patterns)
        self.assertGreater(len(checked), 100)

    def test_components_render_product_links_and_hide_private_products(self):
        self.product2.status = 'draft'; self.product2.save()
        r = self.client.get('/plataforma/componentes/')
        self.assertContains(r, reverse('reino_product', args=[self.store_a.slug, self.product.slug]))
        self.assertNotContains(r, self.product2.short_title)
        self.assertContains(r, reverse('reino_directory'))
        self.assertNotContains(r, '{#')
        self.assertNotContains(r, '#}')

    def test_invalid_hex_theme_returns_validation_error(self):
        config = services_theme.default_config('wiener-kingdom')
        config['colors']['primary'] = '#zzzzzz'
        self.assertTrue(services_theme.validate_config(config))

    def test_wiener_palette_contrast_and_idempotent_release(self):
        config = services_theme.default_config('wiener-kingdom')
        self.assertEqual(config['colors']['ink'], '#101E36')
        self.assertEqual(config['colors']['primary'], '#AF3635')
        self.assertEqual(services_theme.validate_config(config), [])
        call_command('apply_release_theme')  # no production store in this isolated fixture

    def test_other_merchant_cannot_read_legacy_orders(self):
        user = User.objects.create_user('other-store', password='test', is_staff=True)
        MerchantMember.objects.create(user=user, merchant=self.merchant_b, role='owner')
        self.client.force_login(user)
        for route in ['/panel/', '/panel/payments/', '/panel/costs/', '/panel/measurements/']:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 403)

    def test_revoked_merchant_membership_does_not_unlock_legacy_panel(self):
        self.store_a.slug = 'wiener-kingdom'
        self.store_a.save(update_fields=['slug'])
        for merchant in (self.merchant_a, self.merchant_b):
            with self.subTest(merchant=merchant.pk):
                user = User.objects.create_user(f'revoked-{merchant.pk}', is_staff=True)
                member = MerchantMember.objects.create(user=user, merchant=merchant, role='owner')
                self.client.force_login(user)
                if merchant == self.merchant_a:
                    self.assertEqual(self.client.get('/panel/').status_code, 200)
                member.is_active = False  # the same revocation used by team_remove
                member.save(update_fields=['is_active'])
                for route in ['/panel/', '/panel/payments/', '/panel/costs/', '/panel/measurements/']:
                    self.assertEqual(self.client.get(route).status_code, 403)
