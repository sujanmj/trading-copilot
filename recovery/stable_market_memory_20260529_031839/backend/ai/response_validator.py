"""Ensure AI router and callers always receive a normalized response dict."""


def validate_ai_response(result, source='unknown'):
    """Ensure ai_router always returns valid dict with required keys."""
    if result is None:
        return {
            'success': False,
            'text': '',
            'model': '',
            'provider': source,
            'estimated_cost': 0.0,
            'error': 'None returned',
        }

    if isinstance(result, str):
        text = result.strip()
        return {
            'success': bool(text),
            'text': result,
            'model': 'unknown',
            'provider': source,
            'estimated_cost': 0.0,
            'error': None,
        }

    if isinstance(result, dict):
        out = dict(result)
        text = out.get('text')
        if text is None and out.get('response'):
            text = str(out.get('response', ''))
        if text is None and isinstance(out.get('content'), str):
            text = out.get('content', '')
        if text is None:
            text = ''

        success = out.get('success')
        if success is None:
            success = bool(str(text).strip())

        cost = out.get('estimated_cost', 0)
        if cost is None:
            cost = 0.0

        return {
            'success': bool(success),
            'text': str(text),
            'model': out.get('model') or 'unknown',
            'provider': out.get('provider') or source,
            'estimated_cost': float(cost) if cost else 0.0,
            'error': out.get('error') if not success else None,
        }

    return {
        'success': False,
        'text': str(result),
        'model': 'unknown',
        'provider': source,
        'estimated_cost': 0.0,
        'error': f'Unexpected type: {type(result).__name__}',
    }
