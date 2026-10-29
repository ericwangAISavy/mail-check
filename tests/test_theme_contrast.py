"""Check real stylesheet tokens rather than screenshots or a copied palette."""
from pathlib import Path
import re
import pytest

ROOT = Path(__file__).resolve().parents[1]/'frontend/src'


def variables(css, selector):
    match = re.search(selector+r'\s*\{([^}]*)\}', css, re.S)
    return dict(re.findall(r'(--[\w-]+)\s*:\s*([^;]+);', match.group(1))) if match else {}


def palette(mode):
    cyber = (ROOT/'cyber.css').read_text()
    shared = (ROOT/'theme-accessibility.css').read_text() if (ROOT/'theme-accessibility.css').exists() else ''
    values = variables(cyber, r':root, \.dark') | variables(shared, r':root')
    if mode == 'light':
        values |= variables(cyber, r':root\[data-theme="light"\]')
        values |= variables(shared, r':root\[data-theme="light"\]')
    professional=(ROOT/'professional.css').read_text() if (ROOT/'professional.css').exists() else ''
    values |= variables(professional,r':root')
    if mode == 'light':values |= variables(professional,r':root\[data-theme="light"\]')
    return values


def contrast(first, second):
    def luminance(value):
        value = value.strip().lstrip('#')
        if len(value)==3: value=''.join(char*2 for char in value)
        channels = [int(value[i:i+2],16)/255 for i in (0,2,4)]
        channels = [c/12.92 if c<=0.04045 else ((c+0.055)/1.055)**2.4 for c in channels]
        return sum(c*weight for c,weight in zip(channels,(.2126,.7152,.0722)))
    high, low = sorted((luminance(first),luminance(second)), reverse=True)
    return (high+.05)/(low+.05)


@pytest.mark.parametrize('mode', ['dark','light'])
def test_destructive_button_text_has_readable_contrast(mode):
    colors = palette(mode)
    foreground = colors.get('--destructive-foreground', colors['--foreground'])
    assert contrast(foreground, colors['--destructive']) >= 4.5


@pytest.mark.parametrize('mode', ['dark','light'])
def test_shared_scrollbars_and_chart_colors_are_visible(mode):
    colors = palette(mode)
    for key in ('--scrollbar-thumb','--scrollbar-track','--payment-blue','--selection-bg'):
        assert key in colors, f'Missing themed token: {key}'
    assert contrast(colors['--scrollbar-thumb'], colors['--scrollbar-track']) >= 3
    assert contrast(colors['--payment-blue'], colors['--card']) >= 4.5
    assert contrast(colors['--foreground'], colors['--selection-bg']) >= 4.5
    for prefix, count in (('activity',7),('category',10)):
        for index in range(count):
            for background in ('--card','--background'):
                assert contrast(colors[f'--{prefix}-color-{index}'], colors[background]) >= 4.5


@pytest.mark.parametrize('mode', ['dark','light'])
def test_calendar_account_palette_remains_readable_in_each_theme(mode):
    css = (ROOT/'pages/interviews.css').read_text()
    prefix = r'^' if mode == 'dark' else r':root\[data-theme="light"\] '
    rules = re.findall(prefix+r'\.outlook-calendar \.interview-event\.account-color-(\d) \{([^}]*)\}', css, re.M)
    assert {int(index) for index, _ in rules} == set(range(6))
    for _, rule in rules:
        colors = dict(re.findall(r'(--[\w-]+)\s*:\s*([^;]+);',rule))
        foreground = colors.get('--oc-event-text','#ffffff')
        assert contrast(foreground, colors['--oc-event']) >= 4.5


@pytest.mark.parametrize('mode',['dark','light'])
def test_professional_text_controls_and_primary_actions_have_contrast(mode):
    colors=palette(mode)
    for text in ('--foreground','--muted-foreground','--text-soft'):
        for background in ('--background','--card','--surface'):
            assert contrast(colors[text],colors[background])>=4.5,(mode,text,background)
    assert contrast(colors['--primary-foreground'],colors['--primary'])>=4.5
    assert contrast(colors['--input'],colors['--surface'])>=3
