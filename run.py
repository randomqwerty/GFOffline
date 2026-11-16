"""Start the offline GF1 server:  python run.py"""
import logging

from gfserver import app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app.serve()
