import { expect, test } from '@playwright/test'

// Runs against the real stack started by `make test-e2e` (see docs/03-development.en.md, "End-to-end
// tests"): dev_mock synthetic admin, and catalog/services.example.yaml imported at API startup.

test('admin can browse services, confirm a critical execution and import YAML', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Servicios', exact: true })).toBeVisible()
  await page.goto('/services/open-webui')
  await expect(page.getByRole('heading', { name: 'Open WebUI', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Copia de seguridad', exact: true }).click()
  await expect(page.getByText('Confirmar acción crítica')).toBeVisible()
  await page.getByLabel('Motivo (obligatorio)').fill('Prueba de operación')
  await page.getByTestId('critical-confirm').click()
  await expect(page.getByRole('heading', { name: /Ejecución/ })).toBeVisible()
  await page.goto('/catalog')
  await page.getByRole('tab', { name: 'Importar y exportar' }).click()
  await page
    .getByTestId('yaml-input')
    .fill(
      'version: 2\nservices:\n  - id: demo\n    name: Demo\n    group_name: Pruebas\n    environment: homelab',
    )
  await page.getByRole('button', { name: 'Validar (dry-run)' }).click()
  await expect(page.getByText(/Válido:/)).toBeVisible()
})

test('admin sees connectors and resource metadata, never resource content', async ({ page }) => {
  await page.goto('/catalog')
  await page.getByRole('tab', { name: 'Conectores' }).click()
  await expect(page.getByText('https://portainer.404labo.net').first()).toBeVisible()
  await page.getByRole('tab', { name: 'Recursos' }).click()
  await expect(page.getByText('portainer_token', { exact: true })).toBeVisible()
  await expect(page.getByText('fichero portainer_token')).toBeVisible()
  // The API never returns resource content, so no key material can reach the page.
  await expect(page.getByText('PRIVATE KEY')).toHaveCount(0)
})

test('viewer only sees read-only navigation', async ({ page }) => {
  await page.goto('/services/open-webui')
  await expect(page.getByRole('heading', { name: 'Open WebUI', exact: true })).toBeVisible()
  await page.getByTestId('account-menu').click()
  await page.getByText('viewer', { exact: true }).click()
  await expect(page.getByText('Catálogo', { exact: true })).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Reiniciar', exact: true })).toBeDisabled()
})
