module subject(input clk, input rst_n, input clear, input enable,
               input [2:0] amount, output reg [2:0] q);
  wire [3:0] sum = {1'b0, q} + {1'b0, amount};
  always @(posedge clk) begin
    if (!rst_n || clear) q <= 3'd0;
    else if (enable) q <= sum[3] ? 3'd7 : sum[2:0];
  end
endmodule
