import { expect, test } from '@playwright/test'

test('admin can browse services, confirm a critical execution and import YAML', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Servicios', exact: true })).toBeVisible()
  await page.goto('/services/open-webui')
  await expect(page.getByRole('heading', { name: 'Open WebUI', exact: true })).toBeVisible()
  await page
    .locator('.q-item', { hasText: 'Copia de seguridad' })
    .getByRole('button', { name: 'Ejecutar' })
    .click()
  await expect(page.getByText('Confirmar acción crítica')).toBeVisible()
  await page.getByLabel('Motivo (obligatorio)').fill('Prueba de operación')
  await page.getByTestId('critical-confirm').click()
  await expect(page.getByRole('heading', { name: /Ejecución/ })).toBeVisible()
  await page.goto('/catalog')
  await page
    .getByTestId('yaml-input')
    .fill(
      'version: 1\nservices:\n  - id: demo\n    name: Demo\n    group_name: Pruebas\n    environment: homelab',
    )
  await page.getByRole('button', { name: 'Validar (dry-run)' }).click()
  await expect(page.getByText(/Válido:/)).toBeVisible()
})

test('viewer only sees read-only navigation', async ({ page }) => {
  await page.goto('/services/open-webui')
  await expect(page.getByRole('heading', { name: 'Open WebUI', exact: true })).toBeVisible()
  await page.getByTestId('account-menu').click()
  await page.getByText('viewer', { exact: true }).click()
  await expect(page.getByText('Catálogo', { exact: true })).not.toBeVisible()
  await expect(
    page.locator('.q-item', { hasText: 'Reiniciar' }).getByRole('button', { name: 'Ejecutar' }),
  ).toBeDisabled()
})
