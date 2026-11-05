#!/usr/bin/env python3
"""U9 browser acceptance against an offline development server (uses its read-only __scene hook).

From the repo root, start modeling/agents plus Vite dev, then run:
  uv run --all-packages --with playwright python frontend/browser_checks/canvas_drag.py http://localhost:4000 /tmp/u9
Set DEMO_CHECK_BROWSER_EXECUTABLE to an installed Chromium/Chrome executable if needed.
All edits use real mouse/keyboard controls. The hook only reads scene geometry and selection.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    url = sys.argv[1].rstrip('/')
    output = Path(sys.argv[2] if len(sys.argv) > 2 else '/tmp/u9-browser')
    output.mkdir(parents=True, exist_ok=True)
    evidence: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get('DEMO_CHECK_BROWSER_EXECUTABLE'),
            args=['--enable-unsafe-swiftshader'],
        )
        page = browser.new_page(viewport={'width': 1680, 'height': 1050}, reduced_motion='reduce')
        page.set_default_timeout(60_000)
        expect.set_options(timeout=60_000)
        errors: list[str] = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        allowed = {'127.0.0.1', 'localhost', urlparse(url).hostname}
        page.route('**/*', lambda route: route.continue_() if urlparse(route.request.url).hostname in allowed else route.abort())

        def ready() -> None:
            page.wait_for_function('window.__scene?.geometryReady() && window.__scene.store.getState().entities.ship')

        def scene() -> dict:
            return page.evaluate('window.__scene.store.getState()')

        def point(entity_id: str) -> dict:
            ready()
            position = page.evaluate('(id) => window.__scene.screenPositionOf(id)', entity_id)
            assert position is not None, f'No screen position for {entity_id}'
            return position

        def drag(source: dict, target: dict) -> None:
            page.mouse.move(source['x'], source['y'])
            page.mouse.down()
            page.mouse.move(target['x'], target['y'], steps=12)
            page.mouse.up()

        def analysis(action) -> tuple[dict, dict]:
            with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/mooring/analyze')) as requested:
                action()
            request = requested.value
            response = request.response()
            assert response is not None and response.ok, 'Modeling reanalysis failed'
            body, result = request.post_data_json, response.json()
            assert result.get('result_id'), 'Reanalysis did not create a stored result'
            evidence.append({'config': body['config'], 'result_id': result['result_id'], 'status': result['status']})
            return body, result

        try:
            page.goto(url, wait_until='load')
            page.get_by_role('button', name='Open Mooring Assistant', exact=True).click()
            expect(page.get_by_role('tab', name='Setup', exact=True)).to_have_attribute('aria-selected', 'true')
            ready()
            case = page.get_by_label('Demo cases').locator('li').filter(has_text='DDG moderate weather')
            case.get_by_role('button', name='Load', exact=True).click()
            expect(page.get_by_label('Case outcomes')).to_contain_text('validity limited')
            page.get_by_role('tab', name='Lines', exact=True).click()
            expect(page.get_by_text('Overall AMBER', exact=True).first).to_be_visible()
            page.get_by_role('tab', name='Setup', exact=True).click()
            ready()

            # Starboard and port orientations must both update along-pier and off-pier geometry.
            for side in ('starboard', 'port'):
                if side == 'port':
                    analysis(lambda: page.get_by_role('button', name='port', exact=True).click())
                before = scene()['entities']['ship']['pose']
                source = point('ship')

                def move_ship() -> None:
                    page.mouse.move(source['x'], source['y'])
                    page.mouse.down()
                    page.mouse.move(source['x'] + 18, source['y'] - 10, steps=10)
                    assert all(link.get('status') in (None, 'NONE') for link in scene()['links'].values()), 'Old margins remain visible during drag'
                    page.mouse.up()

                body, result = analysis(move_ship)
                after = scene()['entities']['ship']['pose']
                assert body['config']['side_to'] == side
                assert body['config']['standoff_ft'] >= 0
                assert abs(after['x'] - before['x']) > 0.1 and abs(after['y'] - before['y']) > 0.1, 'Both drag axes must change'
                assert math.isclose(body['config']['ship_x_ft'], after['x'] / 0.3048, abs_tol=0.01)
                assert after['headingDeg'] == before['headingDeg'], 'Dragging must not invent an unmodeled yaw'
                assert result['validity']['state'] != 'valid', 'Seed data must stay unqualified'
                print(f'PASS {side} two-axis pointer drag -> modeling request and result {result["result_id"]}', flush=True)

            # Escape restores the previous geometry and line arrangement.
            before = scene()
            source = point('ship')

            def cancel_ship() -> None:
                page.mouse.move(source['x'], source['y'])
                page.mouse.down()
                page.mouse.move(source['x'] + 20, source['y'] - 15, steps=8)
                page.keyboard.press('Escape')
                page.mouse.up()

            analysis(cancel_ship)
            after = scene()
            assert after['entities']['ship']['pose'] == before['entities']['ship']['pose']
            assert set(after['links']) == set(before['links'])
            print('PASS cancelled ship drag preserves geometry and line identities', flush=True)

            # A new line uses the selected type and actual fitting IDs, then reconnect preserves every other field.
            page.get_by_role('tab', name='Lines', exact=True).click()
            before = scene()
            ship_id = next(key for key in before['entities'] if key.startswith('sfit:'))
            pier_ids = [key for key in before['entities'] if key.startswith('pier:')]
            pier_id = min(pier_ids, key=lambda key: abs(before['entities'][key]['pose']['x'] - before['entities'][ship_id]['pose']['x']))
            spec = page.locator('select').filter(has=page.locator('option[value="ARAMID-4S-6IN"]')).first
            spec.select_option('ARAMID-4S-6IN')
            # Click the hull to clear an old selected link before creating a new connection.
            ship_point = point('ship')
            page.mouse.click(ship_point['x'], ship_point['y'])
            body, _ = analysis(lambda: drag(point(ship_id), point(pier_id)))
            assert len(body['config']['lines']) == len(before['links']) + 1
            created = max(body['config']['lines'], key=lambda line: line['line_number'])
            assert created['ship_fitting_id'] == ship_id.removeprefix('sfit:')
            assert created['pier_fitting_id'] == pier_id.removeprefix('pier:')
            assert created['spec_id'] == 'ARAMID-4S-6IN'
            number = created['line_number']
            page.get_by_role('button', name=f'Remove line {number}', exact=True).locator('..').locator('span').first.click()
            assert scene()['selection'] == {'type': 'link', 'id': f'line-{number}'}
            new_pier = min((key for key in pier_ids if key != pier_id), key=lambda key: abs(before['entities'][key]['pose']['x'] - before['entities'][pier_id]['pose']['x']))
            body, _ = analysis(lambda: drag(point(pier_id), point(new_pier)))
            reconnected = next(line for line in body['config']['lines'] if line['line_number'] == number)
            assert reconnected == {**created, 'pier_fitting_id': new_pier.removeprefix('pier:')}
            print('PASS fitting drag creates selected line type; reconnect preserves line identity and remaining fields', flush=True)

            # Invalid water drops retain every endpoint. The scene may request reanalysis, but cannot change the plan.
            before = scene()
            source = point(new_pier)
            analysis(lambda: drag(source, {'x': source['x'], 'y': source['y'] - 170}))
            after = scene()
            assert {key: (link['from'], link['to']) for key, link in before['links'].items()} == {
                key: (link['from'], link['to']) for key, link in after['links'].items()}
            print('PASS invalid fitting drop preserves endpoints', flush=True)

            # Numbered berths are chosen through the world picker, not by changing hidden app state.
            page.get_by_role('tab', name='Setup', exact=True).click()
            page.get_by_role('button', name=re.compile(r'^Port NAVSTA Norfolk, \d+ berths')).click()
            page.get_by_role('button', name='Pier 12 South face (NAVSTA Norfolk)', exact=True).click()
            expect(page.get_by_role('combobox', name='Berth', exact=True)).to_have_value('NAVSTA-NORFOLK-P12-S')
            page.wait_for_function('Object.keys(window.__scene.store.getState().entities).some(id => id.startsWith("pier:P12S-"))')
            print('PASS numbered berth selection updates the scene', flush=True)

            for class_id in ('CG-47', 'LHD-1', 'CVN-68'):
                page.get_by_role('combobox', name='Ship class', exact=True).select_option(class_id)
                expect(page.get_by_label('Selected class capabilities')).to_contain_text('No class-specific mooring fittings')
                page.get_by_role('tab', name='Lines', exact=True).click()
                expect(page.get_by_role('button', name='Recommend layouts', exact=True)).to_be_disabled()
                page.get_by_role('tab', name='Plan & review', exact=True).click()
                expect(page.get_by_role('button', name='Ask the agent to plan', exact=True)).to_be_disabled()
                page.get_by_role('tab', name='Setup', exact=True).click()
                assert not scene()['links'], 'Previous class lines survived the selection'
            print('PASS all three hull-only classes explain and block unsupported planning', flush=True)
            page.get_by_label('Selected class capabilities').scroll_into_view_if_needed()
            page.screenshot(path=str(output / 'class-coverage.png'))
            assert not errors, f'Browser runtime errors: {errors}'
            (output / 'request-evidence.json').write_text(json.dumps(evidence, indent=2))
        except Exception:
            page.screenshot(path=str(output / 'failure.png'))
            raise
        finally:
            browser.close()


if __name__ == '__main__':
    main()
