module proof_counter(input clk, input rst_n, input enable, output reg [3:0] q);
always @(posedge clk) begin
  if (!rst_n) q <= 0;
  else if (enable) q <= q + 1'b1;
end
endmodule
