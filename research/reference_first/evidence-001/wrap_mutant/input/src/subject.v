module subject(input clk, input rst_n, input clear, input enable,
               input [2:0] amount, output reg [2:0] q);
  always @(posedge clk) begin
    if (!rst_n || clear) q <= 3'd0;
    else if (enable) q <= q + amount;
  end
endmodule
