module subject(input clk, input rst_n, input enable, input [3:0] d,
               output reg [3:0] q, output [4:0] combined,
               output reg unknown_control, output reg [3:0] unknown_payload);
  reg [3:0] pending;
  always @(posedge clk) begin
    if (!rst_n) begin q <= 4'd0; pending <= 4'd0; end
    else if (enable) begin pending <= d; q <= pending; end
  end
  assign combined = {1'b0, q} + 5'd1;
endmodule
