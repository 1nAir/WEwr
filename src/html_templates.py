import os

from jinja2 import Environment, FileSystemLoader


def get_base_template(**kwargs) -> str:
    """
    Renders the HTML template using Jinja2.
    Expects kwargs matching the variables in templates/index.html.
    """
    # Determine path to templates directory (one level up from src/)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    templates_dir = os.path.join(base_dir, "templates")

    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("index.html")

    return template.render(**kwargs)
