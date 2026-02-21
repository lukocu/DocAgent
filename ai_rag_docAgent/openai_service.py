from openai import OpenAI

class OpenAIService():

    def __init__(self):
        self.client = OpenAI()