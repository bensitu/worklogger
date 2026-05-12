
import re


def render_template(template_str, data):
    """
    Replace the placeholder {{variable}} in template_str with corresponding values from data dict.
    """

    def replace(match):
        key = match.group(1).strip()
        return str(data.get(key, f"{{{{{key}}}}}"))

    pattern = re.compile(r"\{\{(.*?)\}\}")
    return pattern.sub(replace, template_str)
