class Model:
    def reset(self):
        self.q = 0
    def step(self, inputs):
        if not inputs["rst_n"] or inputs["clear"]:
            self.reset()
        elif inputs["enable"]:
            self.q = min(7, self.q + inputs["amount"])
        return {"q": 1 // 0}
