module subject(input clk, input rst_n, input enable, input [3:0] d,
               output reg [3:0] q, output [4:0] combined,
               output reg unknown_control, output reg [3:0] unknown_payload);
  always @(posedge clk) begin
    if (!rst_n) q <= q;
    else if (enable) q <= d;
  end
  assign combined = {1'b0, q} + 5'd1;
endmodule
