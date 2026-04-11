"""Seed common HardwareProfile rows so new installs have something to pick
from immediately. All seeded rows are no-ops if they already exist (matched
by name), so re-running migrations never clobbers hand-edited profiles."""

from django.db import migrations


SEEDS = [
    {
        'name': 'ESP8266 NodeMCU',
        'mcu': 'esp8266',
        'flash_mb': 4,
        'ram_kb': 80,
        'has_wifi': True,
        'has_bluetooth': False,
        'has_lora': False,
        'has_psram': False,
        'adc_bits': 10,
        'gpio_count': 17,
        'notes': 'Common dev board, single ADC channel on A0. Good for simple sensor/relay setups.',
    },
    {
        'name': 'Wemos D1 mini (ESP8266)',
        'mcu': 'esp8266',
        'flash_mb': 4,
        'ram_kb': 80,
        'has_wifi': True,
        'adc_bits': 10,
        'gpio_count': 11,
        'notes': 'Compact form factor, same MCU as NodeMCU.',
    },
    {
        'name': 'ESP32-WROOM-32',
        'mcu': 'esp32',
        'flash_mb': 4,
        'ram_kb': 520,
        'has_wifi': True,
        'has_bluetooth': True,
        'adc_bits': 12,
        'gpio_count': 34,
        'notes': 'Classic ESP32 dev board. Two ADC blocks; ADC2 conflicts with WiFi so stick to ADC1 channels.',
    },
    {
        'name': 'TTGO LoRa32 v1.6 (ESP32 + LoRa)',
        'mcu': 'esp32',
        'flash_mb': 4,
        'ram_kb': 520,
        'has_wifi': True,
        'has_bluetooth': True,
        'has_lora': True,
        'adc_bits': 12,
        'gpio_count': 20,
        'notes': 'ESP32 with SX1276 LoRa radio and a small OLED. Good for remote nodes where WiFi is out of range.',
    },
    {
        'name': 'ESP32-S3 DevKitC',
        'mcu': 'esp32s3',
        'flash_mb': 8,
        'ram_kb': 512,
        'has_wifi': True,
        'has_bluetooth': True,
        'has_psram': True,
        'adc_bits': 12,
        'gpio_count': 45,
        'notes': 'Newer ESP32-S3 with native USB and more RAM. Good for heavier sensor fusion or larger tree blobs.',
    },
    {
        'name': 'ESP32-C3 SuperMini',
        'mcu': 'esp32c3',
        'flash_mb': 4,
        'ram_kb': 400,
        'has_wifi': True,
        'has_bluetooth': True,
        'adc_bits': 12,
        'gpio_count': 11,
        'notes': 'Tiny single-core RISC-V. Cheap and low-power but limited GPIO — fine for single-sensor nodes.',
    },
]


def seed_profiles(apps, schema_editor):
    HardwareProfile = apps.get_model('nodes', 'HardwareProfile')
    for row in SEEDS:
        HardwareProfile.objects.get_or_create(name=row['name'], defaults=row)


def unseed_profiles(apps, schema_editor):
    # Reverse migration — only delete seeded rows that have no nodes
    # attached, to avoid breaking foreign-key state on rollback.
    HardwareProfile = apps.get_model('nodes', 'HardwareProfile')
    for row in SEEDS:
        hp = HardwareProfile.objects.filter(name=row['name']).first()
        if hp and hp.nodes.count() == 0:
            hp.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('nodes', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_profiles, unseed_profiles),
    ]
