import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import image_engine


class ImageEngineSelectionTests(unittest.TestCase):
    def test_installed_flux4_is_available_and_selectable(self):
        config = Mock()
        config.read_text.return_value = json.dumps({'engine': 'legacy'})
        with patch.object(image_engine, 'CONFIG', config), \
             patch.object(image_engine, 'ready', side_effect=lambda engine=None: engine == 'flux'), \
             patch.object(image_engine, '_save_selection', side_effect=lambda value: value):
            status = image_engine.capabilities()
            options = {item['id']: item for item in status['engine_choices']}
            self.assertTrue(options['flux']['available'])
            saved = image_engine.set_engine('flux')
            self.assertEqual(saved['engine'], 'flux')
            self.assertEqual(saved['preferred_flux_engine'], 'flux')

    def test_reference_fallback_uses_installed_flux4(self):
        config = Mock()
        config.read_text.return_value = json.dumps({'engine': 'sdxl'})
        with patch.object(image_engine, 'CONFIG', config), \
             patch.object(image_engine, 'ready', side_effect=lambda engine=None: engine == 'flux'):
            self.assertEqual(image_engine.preferred_flux_engine(), 'flux')
            self.assertEqual(image_engine.resolve_engine('sdxl', references=True), 'flux')
            self.assertEqual(image_engine.resolve_engine('sdxl', references=True, reference_engine='flux'), 'flux')

    def test_missing_flux4_is_rejected_without_changing_settings(self):
        with patch.object(image_engine, 'ready', return_value=False), \
             patch.object(image_engine, '_save_selection') as save:
            with self.assertRaises(ValueError):
                image_engine.set_engine('flux')
            save.assert_not_called()

    def test_switch_from_flux4_to_flux9_uses_9b_files(self):
        config = Mock()
        config.read_text.return_value = json.dumps({'engine': 'flux', 'preferred_flux_engine': 'flux'})
        with patch.object(image_engine, 'CONFIG', config), \
             patch.object(image_engine, 'ready', side_effect=lambda engine=None: engine == 'flux9'), \
             patch.object(image_engine, '_save_selection', side_effect=lambda value: value):
            choices = {item['id']: item for item in image_engine.capabilities()['engine_choices']}
            self.assertTrue(choices['flux9']['available'])
            saved = image_engine.set_engine('flux9')
            self.assertEqual(saved['engine'], 'flux9')
            self.assertEqual(saved['preferred_flux_engine'], 'flux9')


if __name__ == '__main__':
    unittest.main()
